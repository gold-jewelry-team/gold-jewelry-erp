"""Daily cash count and independent review workflows."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.cash_count import DailyCashCount
from app.models.daily_closing import DailyClosing, DailyClosingPaymentSummary

def create_cash_count(session: Session, *, company_id: UUID, site_id: UUID, closing_id: UUID,
                      opening_cash_float: Decimal, counted_cash_amount: Decimal,
                      counted_by_name: str, count_note: str | None = None) -> DailyCashCount:
    for value, label in ((opening_cash_float, "期初備用金"), (counted_cash_amount, "實際盤點金額")):
        if not isinstance(value, Decimal) or value < 0 or value.quantize(Decimal("0.01")) != value:
            raise ValueError(f"{label}必須是大於或等於零且最多兩位小數的金額。")
    name = counted_by_name.strip()
    if not name:
        raise ValueError("盤點人姓名不可空白。")
    closing = session.execute(select(DailyClosing).where(
        DailyClosing.id == closing_id, DailyClosing.company_id == company_id,
        DailyClosing.site_id == site_id
    ).with_for_update()).scalar_one_or_none()
    if closing is None:
        raise ValueError("找不到指定每日結帳紀錄。")
    exists = session.scalar(select(DailyCashCount.id).where(DailyCashCount.closing_id == closing_id))
    if exists:
        raise ValueError("該結帳紀錄已完成現金盤點，不可重複建立。")
    cash_summary = session.scalar(select(DailyClosingPaymentSummary).where(
        DailyClosingPaymentSummary.closing_id == closing_id,
        DailyClosingPaymentSummary.payment_method == "CASH"
    ))
    cash_net = cash_summary.net_cash_flow if cash_summary else Decimal("0")
    expected = opening_cash_float + cash_net
    variance = counted_cash_amount - expected
    row = DailyCashCount(
        company_id=company_id, site_id=site_id, closing_id=closing_id,
        currency_code="TWD", opening_cash_float=opening_cash_float,
        expected_cash_amount=expected, counted_cash_amount=counted_cash_amount,
        cash_variance=variance, counted_by_name=name, count_note=count_note
    )
    session.add(row)
    session.flush()
    return row

def review_cash_count(session: Session, *, company_id: UUID, site_id: UUID, cash_count_id: UUID,
                      reviewed_by_name: str, review_note: str | None = None) -> DailyCashCount:
    reviewer = reviewed_by_name.strip()
    if not reviewer:
        raise ValueError("覆核人姓名不可空白。")
    row = session.execute(select(DailyCashCount).where(
        DailyCashCount.id == cash_count_id, DailyCashCount.company_id == company_id,
        DailyCashCount.site_id == site_id
    ).with_for_update()).scalar_one_or_none()
    if row is None:
        raise ValueError("找不到指定現金盤點紀錄。")
    if row.reviewed_at is not None:
        raise ValueError("此現金盤點已完成覆核，不可重複覆核。")
    if reviewer.casefold() == row.counted_by_name.casefold():
        raise ValueError("覆核人必須與盤點人不同。")
    row.reviewed_by_name = reviewer
    row.reviewed_at = datetime.now(timezone.utc)
    row.review_note = review_note
    session.flush()
    return row
