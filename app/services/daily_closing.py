"""Daily business closing snapshot generation and closed-day guards."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_closing import DailyClosing, DailyClosingPaymentSummary
from app.models.payment_transaction import PaymentTransaction
from app.models.supplier_payable import SupplierPayment
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.operating_expense import OperatingExpense
from app.models.cash_drawer_movement import CashDrawerMovement

BUSINESS_TIMEZONE = ZoneInfo("Asia/Taipei")
ZERO = Decimal("0")
PAYMENT_METHODS = ("CASH", "CARD", "TRANSFER", "OTHER")


def _day_bounds_utc(business_date: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(business_date, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _business_date(at: datetime) -> date:
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(BUSINESS_TIMEZONE).date()


def assert_business_day_open(
    session: Session, *, site_id: UUID, at: datetime
) -> None:
    """Serialize against closing and prevent transactions after a day's close."""
    site = session.execute(
        select(Site).where(Site.id == site_id).with_for_update()
    ).scalar_one_or_none()
    if site is None:
        raise ValueError("找不到指定營運據點。")
    closed = session.scalar(
        select(DailyClosing.id).where(
            DailyClosing.site_id == site_id,
            DailyClosing.business_date == _business_date(at),
        )
    )
    if closed is not None:
        raise ValueError("該營業日已結帳，不能新增銷售或退貨；請依正式更正流程處理。")


def create_daily_closing(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    business_date: date,
    note: str | None = None,
) -> DailyClosing:
    """Create a one-time snapshot of completed sales and returns for a Taipei day."""
    site = session.execute(
        select(Site).where(Site.id == site_id).with_for_update()
    ).scalar_one_or_none()
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")

    existing = session.scalar(
        select(DailyClosing.id).where(
            DailyClosing.site_id == site_id,
            DailyClosing.business_date == business_date,
        )
    )
    if existing is not None:
        raise ValueError("該據點此營業日已結帳，不可重複結帳。")

    start_at, end_at = _day_bounds_utc(business_date)
    sales = list(session.scalars(
        select(Sale).where(
            Sale.company_id == company_id,
            Sale.site_id == site_id,
            Sale.status == "COMPLETED",
            Sale.completed_at >= start_at,
            Sale.completed_at < end_at,
        )
    ).all())
    sales_by_id = {sale.id: sale for sale in sales}

    returns = list(session.scalars(
        select(SaleReturn).where(
            SaleReturn.company_id == company_id,
            SaleReturn.site_id == site_id,
            SaleReturn.created_at >= start_at,
            SaleReturn.created_at < end_at,
        )
    ).all())

    totals = defaultdict(lambda: {
        "sales_count": 0,
        "returns_count": 0,
        "gross_sales_amount": ZERO,
        "return_reversal_amount": ZERO,
        "collected_amount": ZERO,
        "refunded_amount": ZERO,
        "supplier_paid_amount": ZERO,
        "expenses_paid_amount": ZERO,
        "cash_drawer_in_amount": ZERO,
        "cash_drawer_out_amount": ZERO,
    })
    for sale in sales:
        bucket = totals[sale.payment_method]
        bucket["sales_count"] += 1
        bucket["gross_sales_amount"] += sale.final_amount

    for returned in returns:
        original_sale = sales_by_id.get(returned.sale_id)
        if original_sale is None:
            original_sale = session.get(Sale, returned.sale_id)
        if original_sale is None:
            raise ValueError("退貨紀錄找不到原銷售單，無法正確分類付款方式。")
        bucket = totals[original_sale.payment_method]
        bucket["returns_count"] += 1
        bucket["return_reversal_amount"] += returned.settlement_reversal_amount

    payments = list(session.scalars(
        select(PaymentTransaction).where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.site_id == site_id,
            PaymentTransaction.paid_at >= start_at,
            PaymentTransaction.paid_at < end_at,
        )
    ).all())
    for payment in payments:
        bucket = totals[payment.payment_method]
        if payment.direction == "IN":
            bucket["collected_amount"] += payment.amount
        else:
            bucket["refunded_amount"] += payment.amount

    supplier_payments = list(session.scalars(
        select(SupplierPayment).where(
            SupplierPayment.company_id == company_id,
            SupplierPayment.site_id == site_id,
            SupplierPayment.paid_at >= start_at,
            SupplierPayment.paid_at < end_at,
        )
    ).all())
    for payment in supplier_payments:
        totals[payment.payment_method]["supplier_paid_amount"] += payment.total_amount

    expenses = list(session.scalars(
        select(OperatingExpense).where(
            OperatingExpense.company_id == company_id,
            OperatingExpense.site_id == site_id,
            OperatingExpense.status == "PAID",
            OperatingExpense.paid_at >= start_at,
            OperatingExpense.paid_at < end_at,
        )
    ).all())
    for expense in expenses:
        totals[expense.payment_method]["expenses_paid_amount"] += expense.amount

    drawer_movements = list(session.scalars(
        select(CashDrawerMovement).where(
            CashDrawerMovement.company_id == company_id,
            CashDrawerMovement.site_id == site_id,
            CashDrawerMovement.created_at >= start_at,
            CashDrawerMovement.created_at < end_at,
        )
    ).all())
    cash_bucket = totals["CASH"]
    for movement in drawer_movements:
        if movement.direction == "IN":
            cash_bucket["cash_drawer_in_amount"] += movement.amount
        else:
            cash_bucket["cash_drawer_out_amount"] += movement.amount

    total_collected = sum((p.amount for p in payments if p.direction == "IN"), ZERO)
    total_refunded = sum((p.amount for p in payments if p.direction == "OUT"), ZERO)
    total_supplier_paid = sum((p.total_amount for p in supplier_payments), ZERO)
    total_expenses_paid = sum((e.amount for e in expenses), ZERO)
    total_drawer_in = sum((m.amount for m in drawer_movements if m.direction == "IN"), ZERO)
    total_drawer_out = sum((m.amount for m in drawer_movements if m.direction == "OUT"), ZERO)

    closing = DailyClosing(
        company_id=company_id,
        site_id=site_id,
        business_date=business_date,
        currency_code="TWD",
        sales_count=len(sales),
        returns_count=len(returns),
        gross_sales_amount=sum(
            (sale.final_amount for sale in sales), ZERO
        ),
        return_reversal_amount=sum(
            (returned.settlement_reversal_amount for returned in returns), ZERO
        ),
        net_sales_amount=(
            sum((sale.final_amount for sale in sales), ZERO)
            + sum((returned.settlement_reversal_amount for returned in returns), ZERO)
        ),
        collected_amount=total_collected,
        refunded_amount=total_refunded,
        supplier_paid_amount=total_supplier_paid,
        expenses_paid_amount=total_expenses_paid,
        cash_drawer_in_amount=total_drawer_in,
        cash_drawer_out_amount=total_drawer_out,
        net_cash_flow=total_collected - total_refunded - total_supplier_paid - total_expenses_paid,
        note=note,
    )
    session.add(closing)
    session.flush()

    for payment_method in PAYMENT_METHODS:
        bucket = totals[payment_method]
        if not any(bucket.values()):
            continue
        sales_amount = bucket["gross_sales_amount"]
        reversal_amount = bucket["return_reversal_amount"]
        session.add(DailyClosingPaymentSummary(
            closing_id=closing.id,
            payment_method=payment_method,
            sales_count=bucket["sales_count"],
            returns_count=bucket["returns_count"],
            gross_sales_amount=sales_amount,
            return_reversal_amount=reversal_amount,
            net_sales_amount=sales_amount + reversal_amount,
            collected_amount=bucket["collected_amount"],
            refunded_amount=bucket["refunded_amount"],
            supplier_paid_amount=bucket["supplier_paid_amount"],
            expenses_paid_amount=bucket["expenses_paid_amount"],
            cash_drawer_in_amount=bucket["cash_drawer_in_amount"],
            cash_drawer_out_amount=bucket["cash_drawer_out_amount"],
            net_cash_flow=(
                bucket["collected_amount"]
                - bucket["refunded_amount"]
                - bucket["supplier_paid_amount"]
                - bucket["expenses_paid_amount"]
            ),
        ))
    session.flush()
    return closing
