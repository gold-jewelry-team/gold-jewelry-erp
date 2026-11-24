"""Current open receivables, return settlements, customer-order balances and supplier payables."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.customer_order import CustomerOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.supplier_payable import SupplierBill

BUSINESS_TIMEZONE = ZoneInfo("Asia/Taipei")
ZERO = Decimal("0.00")
DISPLAY_LIMIT_PER_CATEGORY = 200


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def build_outstanding_balance_report(session, *, company_id: UUID, site_id: UUID) -> dict:
    """Build current balances from source ledgers; never add amounts across currencies."""
    now = datetime.now(timezone.utc)
    today = now.astimezone(BUSINESS_TIMEZONE).date()

    payments = session.scalars(select(PaymentTransaction).where(
        PaymentTransaction.company_id == company_id,
        PaymentTransaction.site_id == site_id,
    )).all()
    sale_paid: dict[UUID, Decimal] = {}
    return_paid: dict[UUID, Decimal] = {}
    for payment in payments:
        if payment.sale_id is not None:
            sale_paid[payment.sale_id] = sale_paid.get(payment.sale_id, ZERO) + (
                payment.amount if payment.direction == "IN" else -payment.amount
            )
        elif payment.sale_return_id is not None:
            return_paid[payment.sale_return_id] = return_paid.get(payment.sale_return_id, ZERO) + (
                payment.amount if payment.direction == "IN" else -payment.amount
            )

    grouped: dict[str, list[dict]] = {}

    def add_item(currency: str, item: dict) -> None:
        item["currency_code"] = currency
        grouped.setdefault(currency, []).append(item)

    sales = session.scalars(select(Sale).where(
        Sale.company_id == company_id,
        Sale.site_id == site_id,
        Sale.status == "COMPLETED",
    ).order_by(Sale.completed_at.desc())).all()
    for sale in sales:
        expected_direction = "IN" if sale.final_amount >= 0 else "OUT"
        settled = sale_paid.get(sale.id, ZERO)
        # Sale payment direction follows the sale amount's sign.
        if expected_direction == "OUT":
            settled = -settled
        outstanding = abs(sale.final_amount) - settled
        if outstanding > ZERO:
            add_item(sale.currency_code, {
                "category": "SALE_RECEIVABLE",
                "side": "RECEIVABLE",
                "source_target": "salesPanel",
                "category_label": "銷售待收尾款",
                "document_id": str(sale.id),
                "document_no": sale.sale_no,
                "amount": _money(outstanding),
                "status": "OPEN",
                "event_date": sale.completed_at,
                "due_date": None,
                "days_overdue": None,
                "detail": "已完成銷售單尚未收清",
            })

    returns = session.scalars(select(SaleReturn).where(
        SaleReturn.company_id == company_id,
        SaleReturn.site_id == site_id,
    ).order_by(SaleReturn.created_at.desc())).all()
    for returned in returns:
        obligation = returned.settlement_reversal_amount
        if obligation == ZERO:
            continue
        direction = "IN" if obligation > 0 else "OUT"
        settled = return_paid.get(returned.id, ZERO)
        if direction == "OUT":
            settled = -settled
        outstanding = abs(obligation) - settled
        if outstanding > ZERO:
            add_item(returned.currency_code, {
                "category": "RETURN_RECEIVABLE" if direction == "IN" else "RETURN_REFUND_PAYABLE",
                "source_target": "salesPanel",
                "side": "RECEIVABLE" if direction == "IN" else "PAYABLE",
                "category_label": "退貨待收款" if direction == "IN" else "退貨待退款",
                "document_id": str(returned.id),
                "document_no": returned.return_no,
                "amount": _money(outstanding),
                "status": "OPEN",
                "event_date": returned.created_at,
                "due_date": None,
                "days_overdue": None,
                "detail": "退貨結算金額尚未完成實際收付",
            })

    orders = session.scalars(select(CustomerOrder).where(
        CustomerOrder.company_id == company_id,
        CustomerOrder.site_id == site_id,
        CustomerOrder.status.in_(("PENDING_DEPOSIT", "IN_PROGRESS", "ARRIVED", "READY")),
    ).order_by(CustomerOrder.expected_delivery_date, CustomerOrder.created_at.desc())).all()
    for order in orders:
        outstanding = order.total_amount - order.deposit_amount
        if outstanding > ZERO:
            expected_date = order.expected_delivery_date
            due_date = (
                expected_date.astimezone(BUSINESS_TIMEZONE).date()
                if expected_date is not None and expected_date.tzinfo is not None
                else expected_date.date() if expected_date is not None else None
            )
            add_item(order.currency_code, {
                "category": "CUSTOMER_ORDER_BALANCE",
                "side": "RECEIVABLE",
                "source_target": "customerOrderList",
                "category_label": "客訂待收尾款",
                "document_id": str(order.id),
                "document_no": order.order_no,
                "amount": _money(outstanding),
                "status": order.status,
                "event_date": order.created_at,
                "due_date": due_date,
                "days_overdue": (today - due_date).days if due_date and due_date < today else 0 if due_date else None,
                "detail": f"客戶：{order.customer_name}；訂單總額 {_money(order.total_amount)}，已收 {_money(order.deposit_amount)}",
            })

    bills = session.scalars(select(SupplierBill).options(
        selectinload(SupplierBill.allocations),
        selectinload(SupplierBill.gold_allocations),
    ).where(
        SupplierBill.company_id == company_id,
        SupplierBill.site_id == site_id,
        SupplierBill.status != "VOID",
    ).order_by(SupplierBill.due_date, SupplierBill.bill_date.desc())).all()
    for bill in bills:
        outstanding = bill.outstanding_amount
        if outstanding > ZERO:
            days_overdue = (
                (today - bill.due_date).days
                if bill.due_date is not None and bill.due_date < today else
                0 if bill.due_date is not None else None
            )
            add_item(bill.currency_code, {
                "category": "SUPPLIER_PAYABLE",
                "side": "PAYABLE",
                "source_target": "supplierPayablesPanel",
                "category_label": "供應商待付款",
                "document_id": str(bill.id),
                "document_no": bill.bill_no,
                "amount": _money(outstanding),
                "status": bill.status,
                "event_date": bill.bill_date,
                "due_date": bill.due_date,
                "days_overdue": days_overdue,
                "detail": f"帳單總額 {_money(bill.total_amount)}，已結清 {_money(bill.paid_amount)}（含現金付款及黃金折抵）",
            })

    categories = ("SALE_RECEIVABLE", "RETURN_RECEIVABLE", "RETURN_REFUND_PAYABLE", "CUSTOMER_ORDER_BALANCE", "SUPPLIER_PAYABLE")
    summaries = []
    items = []
    for currency, currency_items in sorted(grouped.items()):
        by_category = []
        for category in categories:
            selected = [item for item in currency_items if item["category"] == category]
            if selected:
                by_category.append({
                    "category": category,
                    "label": selected[0]["category_label"],
                    "count": len(selected),
                    "amount": _money(sum((Decimal(item["amount"]) for item in selected), ZERO)),
                })
        summaries.append({
            "currency_code": currency,
            "item_count": len(currency_items),
            "total_receivable": _money(sum((Decimal(item["amount"]) for item in currency_items if item["side"] == "RECEIVABLE"), ZERO)),
            "total_payable": _money(sum((Decimal(item["amount"]) for item in currency_items if item["side"] == "PAYABLE"), ZERO)),
            "by_category": by_category,
        })
        for category in categories:
            items.extend([
                item for item in currency_items if item["category"] == category
            ][:DISPLAY_LIMIT_PER_CATEGORY])

    items.sort(key=lambda item: (
        item["days_overdue"] is None,
        -(item["days_overdue"] or 0),
        item["due_date"] or date.max,
        str(item["event_date"] or ""),
    ))
    return {
        "as_of": now,
        "timezone": "Asia/Taipei",
        "summaries_by_currency": summaries,
        "items": items,
        "display_limit_per_category": DISPLAY_LIMIT_PER_CATEGORY,
    }
