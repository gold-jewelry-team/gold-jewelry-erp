"""Read-only, event-date-based operational reports for a store and period.

Sales and returns are reported on their completion/return dates. Actual customer
payments, supplier disbursements, paid expenses and cash-drawer movements are
reported on their own event timestamps. Amounts are never combined across
currencies.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.operating_expense import OperatingExpense
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.supplier_payable import SupplierPayment

BUSINESS_TIMEZONE = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
ZERO = Decimal("0.00")


def _period_bounds_utc(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    if period_end < period_start:
        raise ValueError("報表結束日不可早於開始日。")
    if period_end == date.max:
        raise ValueError("報表結束日超出可查詢範圍。")
    start_local = datetime.combine(period_start, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=BUSINESS_TIMEZONE)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _business_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(BUSINESS_TIMEZONE).date()


def _new_bucket() -> dict:
    return {
        "sales_count": 0,
        "gross_sales_amount": ZERO,
        "returns_count": 0,
        "return_reversal_amount": ZERO,
        "sales_collected_amount": ZERO,
        "sales_refunded_amount": ZERO,
        "return_collected_amount": ZERO,
        "return_refunded_amount": ZERO,
        "customer_order_collected_amount": ZERO,
        "customer_order_refunded_amount": ZERO,
        "customer_collected_amount": ZERO,
        "customer_refunded_amount": ZERO,
        "supplier_payment_count": 0,
        "supplier_paid_amount": ZERO,
        "paid_expense_count": 0,
        "expenses_paid_amount": ZERO,
        "cash_drawer_in_amount": ZERO,
        "cash_drawer_out_amount": ZERO,
        "payment_methods": {},
    }


def _new_method_bucket() -> dict:
    return {
        "customer_collected_amount": ZERO,
        "customer_refunded_amount": ZERO,
        "supplier_paid_amount": ZERO,
        "expenses_paid_amount": ZERO,
        "cash_drawer_in_amount": ZERO,
        "cash_drawer_out_amount": ZERO,
    }


def _add_amount(
    bucket: dict,
    key: str,
    amount: Decimal,
    payment_method: str | None = None,
) -> None:
    bucket[key] += amount
    if payment_method is not None:
        method_bucket = bucket["payment_methods"].setdefault(
            payment_method, _new_method_bucket()
        )
        method_bucket[key] += amount


def _add_count(bucket: dict, key: str, count: int = 1) -> None:
    bucket[key] += count


def _serialize_bucket(bucket: dict) -> dict:
    result = {key: value for key, value in bucket.items() if key != "payment_methods"}
    result["net_sales_amount"] = (
        bucket["gross_sales_amount"] + bucket["return_reversal_amount"]
    )
    result["net_customer_cash_flow"] = (
        bucket["customer_collected_amount"] - bucket["customer_refunded_amount"]
    )
    result["net_operating_cash_flow"] = (
        result["net_customer_cash_flow"]
        - bucket["supplier_paid_amount"]
        - bucket["expenses_paid_amount"]
    )
    # This is the expected change in physical cash, not total operating cash flow.
    result["expected_cash_change"] = (
        bucket["payment_methods"].get("CASH", {}).get("customer_collected_amount", ZERO)
        - bucket["payment_methods"].get("CASH", {}).get("customer_refunded_amount", ZERO)
        - bucket["payment_methods"].get("CASH", {}).get("supplier_paid_amount", ZERO)
        - bucket["payment_methods"].get("CASH", {}).get("expenses_paid_amount", ZERO)
        + bucket["cash_drawer_in_amount"]
        - bucket["cash_drawer_out_amount"]
    )
    # Keep monetary values as fixed-point strings in JSON. Returning Decimal
    # through an untyped dict would otherwise be encoded as binary floats.
    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = format(value, ".2f")

    result["payment_methods"] = []
    for method, values in sorted(bucket["payment_methods"].items()):
        method_result = {"payment_method": method, **values}
        method_result["net_operating_cash_flow"] = (
            values["customer_collected_amount"]
            - values["customer_refunded_amount"]
            - values["supplier_paid_amount"]
            - values["expenses_paid_amount"]
        )
        for key, value in list(method_result.items()):
            if isinstance(value, Decimal):
                method_result[key] = format(value, ".2f")
        result["payment_methods"].append(method_result)
    return result


def _format_check_value(value) -> str:
    if isinstance(value, Decimal):
        return format(value, ".2f")
    return str(value)


def _build_integrity_checks(
    totals: dict[str, dict],
    daily: dict[tuple[date, str], dict],
) -> list[dict]:
    """Validate arithmetic invariants without assuming sales equal same-day receipts."""
    checks: list[dict] = []

    def add(currency: str, code: str, label: str, actual, expected) -> None:
        passed = actual == expected
        checks.append({
            "currency_code": currency,
            "code": code,
            "label": label,
            "status": "PASS" if passed else "ERROR",
            "actual": _format_check_value(actual),
            "expected": _format_check_value(expected),
        })

    amount_fields = (
        "gross_sales_amount",
        "return_reversal_amount",
        "sales_collected_amount",
        "sales_refunded_amount",
        "return_collected_amount",
        "return_refunded_amount",
        "customer_order_collected_amount",
        "customer_order_refunded_amount",
        "customer_collected_amount",
        "customer_refunded_amount",
        "supplier_paid_amount",
        "expenses_paid_amount",
        "cash_drawer_in_amount",
        "cash_drawer_out_amount",
    )
    count_fields = ("sales_count", "returns_count", "supplier_payment_count", "paid_expense_count")
    method_fields = (
        "customer_collected_amount",
        "customer_refunded_amount",
        "supplier_paid_amount",
        "expenses_paid_amount",
        "cash_drawer_in_amount",
        "cash_drawer_out_amount",
    )

    for currency, bucket in sorted(totals.items()):
        daily_buckets = [
            day_bucket for (business_date, day_currency), day_bucket in daily.items()
            if day_currency == currency
        ]
        daily_net_sales = sum(
            (row["gross_sales_amount"] + row["return_reversal_amount"]
             for row in daily_buckets),
            ZERO,
        )
        add(
            currency, "net_sales", "銷售淨額與每日加總",
            bucket["gross_sales_amount"] + bucket["return_reversal_amount"],
            daily_net_sales,
        )
        add(
            currency, "customer_collected_sources", "客戶收款來源加總",
            bucket["customer_collected_amount"],
            bucket["sales_collected_amount"] + bucket["return_collected_amount"]
            + bucket["customer_order_collected_amount"],
        )
        add(
            currency, "customer_refunded_sources", "客戶退款來源加總",
            bucket["customer_refunded_amount"],
            bucket["sales_refunded_amount"] + bucket["return_refunded_amount"]
            + bucket["customer_order_refunded_amount"],
        )
        period_net_operating = (
            bucket["customer_collected_amount"] - bucket["customer_refunded_amount"]
            - bucket["supplier_paid_amount"] - bucket["expenses_paid_amount"]
        )
        daily_net_operating = sum((
            row["customer_collected_amount"] - row["customer_refunded_amount"]
            - row["supplier_paid_amount"] - row["expenses_paid_amount"]
            for row in daily_buckets
        ), ZERO)
        add(
            currency, "net_operating_cash_flow", "營運現金流與每日加總",
            period_net_operating, daily_net_operating,
        )
\n        def cash_change(row):
            cash = row["payment_methods"].get("CASH", {})
            return (
                cash.get("customer_collected_amount", ZERO)
                - cash.get("customer_refunded_amount", ZERO)
                - cash.get("supplier_paid_amount", ZERO)
                - cash.get("expenses_paid_amount", ZERO)
                + row["cash_drawer_in_amount"] - row["cash_drawer_out_amount"]
            )
        add(
            currency, "expected_cash_change", "現金櫃預期變動與每日加總",
            cash_change(bucket), sum((cash_change(row) for row in daily_buckets), ZERO),
        )
        daily_matches = all(
            sum((row.get(field, 0) for row in daily_buckets), 0) == bucket[field]
            for field in (*amount_fields, *count_fields)
        )
        add(
            currency, "daily_totals", "每日明細與期間總覽加總",
            "一致" if daily_matches else "不一致",
            "一致",
        )

        method_matches = all(
            sum(
                (method_bucket.get(field, ZERO)
                 for method_bucket in bucket["payment_methods"].values()),
                ZERO,
            ) == bucket[field]
            for field in method_fields
        )
        add(
            currency, "payment_method_totals", "付款方式與期間總額加總",
            "一致" if method_matches else "不一致",
            "一致",
        )

    return checks


def build_operational_period_report(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    period_start: date,
    period_end: date,
) -> dict:
    """Build an auditable period summary using each record's own event timestamp."""
    start_at, end_at = _period_bounds_utc(period_start, period_end)
    site = session.scalar(
        select(Site).where(
            Site.id == site_id,
            Site.company_id == company_id,
        )
    )
    if site is None:
        raise ValueError("據點不存在或不屬於指定公司。")

    totals: dict[str, dict] = {}
    daily: dict[tuple[date, str], dict] = {}

    def buckets(currency_code: str, occurred_at: datetime) -> tuple[dict, dict]:
        business_date = _business_date(occurred_at)
        total_bucket = totals.setdefault(currency_code, _new_bucket())
        day_bucket = daily.setdefault((business_date, currency_code), _new_bucket())
        return total_bucket, day_bucket

    def add_amount(
        currency_code: str,
        occurred_at: datetime,
        key: str,
        amount: Decimal,
        payment_method: str | None = None,
    ) -> None:
        total_bucket, day_bucket = buckets(currency_code, occurred_at)
        _add_amount(total_bucket, key, amount, payment_method)
        _add_amount(day_bucket, key, amount, payment_method)

    def add_count(currency_code: str, occurred_at: datetime, key: str) -> None:
        total_bucket, day_bucket = buckets(currency_code, occurred_at)
        _add_count(total_bucket, key)
        _add_count(day_bucket, key)

    sales = list(session.scalars(
        select(Sale).where(
            Sale.company_id == company_id,
            Sale.site_id == site_id,
            Sale.status == "COMPLETED",
            Sale.completed_at >= start_at,
            Sale.completed_at < end_at,
        )
    ).all())
    for sale in sales:
        occurred_at = sale.completed_at
        add_count(sale.currency_code, occurred_at, "sales_count")
        add_amount(
            sale.currency_code,
            occurred_at,
            "gross_sales_amount",
            sale.final_amount,
        )

    returns = list(session.scalars(
        select(SaleReturn).where(
            SaleReturn.company_id == company_id,
            SaleReturn.site_id == site_id,
            SaleReturn.created_at >= start_at,
            SaleReturn.created_at < end_at,
        )
    ).all())
    for returned in returns:
        add_count(returned.currency_code, returned.created_at, "returns_count")
        add_amount(
            returned.currency_code,
            returned.created_at,
            "return_reversal_amount",
            returned.settlement_reversal_amount,
        )

    payments = list(session.scalars(
        select(PaymentTransaction).where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.site_id == site_id,
            PaymentTransaction.paid_at >= start_at,
            PaymentTransaction.paid_at < end_at,
        )
    ).all())
    for payment in payments:
        if payment.direction == "IN":
            total_key = "customer_collected_amount"
            source_key = (
                "sales_collected_amount" if payment.sale_id is not None
                else "return_collected_amount" if payment.sale_return_id is not None
                else "customer_order_collected_amount"
            )
        else:
            total_key = "customer_refunded_amount"
            source_key = (
                "sales_refunded_amount" if payment.sale_id is not None
                else "return_refunded_amount" if payment.sale_return_id is not None
                else "customer_order_refunded_amount"
            )
        add_amount(
            payment.currency_code, payment.paid_at, total_key,
            payment.amount, payment.payment_method,
        )
        add_amount(payment.currency_code, payment.paid_at, source_key, payment.amount)

    supplier_payments = list(session.scalars(
        select(SupplierPayment).where(
            SupplierPayment.company_id == company_id,
            SupplierPayment.site_id == site_id,
            SupplierPayment.paid_at >= start_at,
            SupplierPayment.paid_at < end_at,
        )
    ).all())
    for payment in supplier_payments:
        add_count(payment.currency_code, payment.paid_at, "supplier_payment_count")
        add_amount(
            payment.currency_code, payment.paid_at, "supplier_paid_amount",
            payment.total_amount, payment.payment_method,
        )

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
        add_count(expense.currency_code, expense.paid_at, "paid_expense_count")
        add_amount(
            expense.currency_code, expense.paid_at, "expenses_paid_amount",
            expense.amount, expense.payment_method,
        )

    drawer_movements = list(session.scalars(
        select(CashDrawerMovement).where(
            CashDrawerMovement.company_id == company_id,
            CashDrawerMovement.site_id == site_id,
            CashDrawerMovement.created_at >= start_at,
            CashDrawerMovement.created_at < end_at,
        )
    ).all())
    for movement in drawer_movements:
        key = (
            "cash_drawer_in_amount"
            if movement.direction == "IN"
            else "cash_drawer_out_amount"
        )
        add_amount(movement.currency_code, movement.created_at, key, movement.amount, "CASH")

    totals_by_currency = [
        {"currency_code": currency, **_serialize_bucket(bucket)}
        for currency, bucket in sorted(totals.items())
    ]
    daily_rows = [
        {
            "business_date": business_date,
            "currency_code": currency,
            **_serialize_bucket(bucket),
        }
        for (business_date, currency), bucket in sorted(daily.items())
    ]
    return {
        "company_id": company_id,
        "site_id": site_id,
        "site_name": site.name,
        "timezone": "Asia/Taipei",
        "period_start": period_start,
        "period_end": period_end,
        "totals_by_currency": totals_by_currency,
        "daily": daily_rows,
        "integrity_checks": _build_integrity_checks(totals, daily),
    }
