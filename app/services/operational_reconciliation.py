"""Cross-check daily closing snapshots, physical cash counts and bank cash movements."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.bank_account import BankTransaction
from app.models.cash_count import DailyCashCount
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.daily_closing import DailyClosing

BUSINESS_TIMEZONE = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
ZERO = Decimal("0.00")


def _bounds(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    start = datetime.combine(period_start, time.min, tzinfo=BUSINESS_TIMEZONE)
    end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=BUSINESS_TIMEZONE)
    return start.astimezone(UTC), end.astimezone(UTC)


def _money(value: Decimal | None) -> str:
    return format(value or ZERO, ".2f")


def build_daily_closing_reconciliation(
    session,
    *,
    company_id: UUID,
    site_id: UUID,
    period_start: date,
    period_end: date,
    daily_rows: list[dict],
) -> dict:
    """Compare immutable close snapshots with event-date report and count records."""
    start_at, end_at = _bounds(period_start, period_end)
    daily_twd = {
        row["business_date"]: row
        for row in daily_rows
        if row["currency_code"] == "TWD"
    }
    closings = list(session.scalars(
        select(DailyClosing).where(
            DailyClosing.company_id == company_id,
            DailyClosing.site_id == site_id,
            DailyClosing.business_date >= period_start,
            DailyClosing.business_date <= period_end,
        ).order_by(DailyClosing.business_date)
    ).all())
    closing_by_date = {row.business_date: row for row in closings}
    counts_by_closing = {}
    if closings:
        count_rows = session.scalars(
            select(DailyCashCount).where(
                DailyCashCount.company_id == company_id,
                DailyCashCount.site_id == site_id,
                DailyCashCount.closing_id.in_([row.id for row in closings]),
            )
        ).all()
        counts_by_closing = {row.closing_id: row for row in count_rows}

    fields = (
        ("sales_count", "銷售筆數", "sales_count"),
        ("returns_count", "退貨筆數", "returns_count"),
        ("gross_sales_amount", "銷售總額", "gross_sales_amount"),
        ("return_reversal_amount", "退貨沖銷金額", "return_reversal_amount"),
        ("collected_amount", "客戶實際收款", "customer_collected_amount"),
        ("refunded_amount", "客戶實際退款", "customer_refunded_amount"),
        ("supplier_paid_amount", "供應商付款", "supplier_paid_amount"),
        ("expenses_paid_amount", "已付款營業費用", "expenses_paid_amount"),
        ("cash_drawer_in_amount", "現金櫃存入", "cash_drawer_in_amount"),
        ("cash_drawer_out_amount", "現金櫃支出", "cash_drawer_out_amount"),
    )
    dates = sorted(set(daily_twd) | set(closing_by_date))
    daily_checks = []
    for business_date in dates:
        closing = closing_by_date.get(business_date)
        report = daily_twd.get(business_date, {})
        if closing is None:
            daily_checks.append({
                "business_date": business_date,
                "status": "NOT_CLOSED",
                "closing_id": None,
                "checks": [],
                "cash_count": None,
            })
            continue

        checks = []
        for closing_field, label, report_field in fields:
            actual = getattr(closing, closing_field)
            expected = report.get(report_field, 0)
            if isinstance(actual, Decimal):
                expected_value = Decimal(str(expected or "0"))
                passed = actual == expected_value
                actual_value = _money(actual)
                expected_display = _money(expected_value)
            else:
                passed = actual == int(expected or 0)
                actual_value = str(actual)
                expected_display = str(int(expected or 0))
            checks.append({
                "code": closing_field,
                "label": label,
                "status": "PASS" if passed else "ERROR",
                "actual": actual_value,
                "expected": expected_display,
            })

        cash_count = counts_by_closing.get(closing.id)
        count_result = None
        if cash_count is None:
            count_status = "MISSING_COUNT"
        else:
            report_cash_change = Decimal(str(report.get("expected_cash_change", "0.00")))
            expected_from_report = cash_count.opening_cash_float + report_cash_change
            expected_matches = cash_count.expected_cash_amount == expected_from_report
            variance = cash_count.cash_variance
            if not expected_matches:
                count_status = "ERROR"
            elif variance == ZERO:
                count_status = "PASS"
            elif cash_count.reviewed_at is None:
                count_status = "NEEDS_REVIEW"
            else:
                count_status = "REVIEWED_WITH_VARIANCE"
            count_result = {
                "id": str(cash_count.id),
                "status": count_status,
                "opening_cash_float": _money(cash_count.opening_cash_float),
                "expected_cash_amount": _money(cash_count.expected_cash_amount),
                "expected_from_operational_report": _money(expected_from_report),
                "counted_cash_amount": _money(cash_count.counted_cash_amount),
                "cash_variance": _money(variance),
                "counted_by_name": cash_count.counted_by_name,
                "counted_at": cash_count.counted_at,
                "reviewed_by_name": cash_count.reviewed_by_name,
                "reviewed_at": cash_count.reviewed_at,
                "review_note": cash_count.review_note,
            }
        snapshot_passed = all(item["status"] == "PASS" for item in checks)
        if not snapshot_passed or count_status == "ERROR":
            status = "ERROR"
        elif count_status == "MISSING_COUNT":
            status = "NEEDS_COUNT"
        elif count_status == "NEEDS_REVIEW":
            status = "NEEDS_REVIEW"
        elif count_status == "REVIEWED_WITH_VARIANCE":
            status = "REVIEWED_WITH_VARIANCE"
        else:
            status = "PASS"
        daily_checks.append({
            "business_date": business_date,
            "status": status,
            "closing_id": str(closing.id),
            "checks": checks,
            "cash_count": count_result,
        })

    bank_transactions = list(session.scalars(
        select(BankTransaction).where(
            BankTransaction.company_id == company_id,
            BankTransaction.site_id == site_id,
            BankTransaction.transaction_type.in_(("CASH_DEPOSIT", "CASH_WITHDRAWAL")),
            BankTransaction.occurred_at >= start_at,
            BankTransaction.occurred_at < end_at,
        ).order_by(BankTransaction.occurred_at)
    ).all())
    bank_checks = []
    for bank_tx in bank_transactions:
        movement = session.scalar(select(CashDrawerMovement).where(
            CashDrawerMovement.bank_transaction_id == bank_tx.id,
            CashDrawerMovement.company_id == company_id,
            CashDrawerMovement.site_id == site_id,
        ))
        expected_type = (
            "BANK_DEPOSIT" if bank_tx.transaction_type == "CASH_DEPOSIT"
            else "BANK_WITHDRAWAL"
        )
        expected_direction = "OUT" if bank_tx.transaction_type == "CASH_DEPOSIT" else "IN"
        if movement is None:
            status = "ERROR"
            actual = None
        else:
            actual = {
                "movement_id": str(movement.id),
                "movement_type": movement.movement_type,
                "direction": movement.direction,
                "amount": _money(movement.amount),
            }
            status = (
                "PASS"
                if movement.movement_type == expected_type
                and movement.direction == expected_direction
                and movement.amount == bank_tx.amount
                and movement.currency_code == bank_tx.currency_code
                else "ERROR"
            )
        bank_checks.append({
            "bank_transaction_id": str(bank_tx.id),
            "transaction_type": bank_tx.transaction_type,
            "description": bank_tx.description,
            "amount": _money(bank_tx.amount),
            "currency_code": bank_tx.currency_code,
            "expected_drawer_movement_type": expected_type,
            "expected_drawer_direction": expected_direction,
            "actual_drawer_movement": actual,
            "status": status,
        })

    bank_errors = sum(1 for row in bank_checks if row["status"] != "PASS")
    daily_errors = sum(1 for row in daily_checks if row["status"] == "ERROR")
    pending_counts = sum(
        1 for row in daily_checks if row["status"] in ("NEEDS_COUNT", "NEEDS_REVIEW")
    )
    return {
        "daily_closings": daily_checks,
        "daily_closing_summary": {
            "days_checked": len(daily_checks),
            "errors": daily_errors,
            "pending": pending_counts,
        },
        "bank_cash_movements": bank_checks,
        "bank_cash_movement_summary": {
            "transactions_checked": len(bank_checks),
            "errors": bank_errors,
        },
    }
