"""Append-only customer collection and refund transaction services."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.services.daily_closing import assert_business_day_open

PAYMENT_METHODS = {"CASH", "CARD", "TRANSFER", "OTHER"}
CENT = Decimal("0.01")


def _validate_amount(amount: Decimal) -> None:
    if not isinstance(amount, Decimal) or amount <= 0:
        raise ValueError("收付款金額必須是正數 Decimal。")
    if amount.quantize(CENT) != amount:
        raise ValueError("收付款金額最多只能有小數點後兩位。")


def _validate_method(payment_method: str) -> None:
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("不支援的收付款方式。")


def _existing_amount(
    session: Session, *, sale_id: UUID | None = None, sale_return_id: UUID | None = None,
    direction: str,
) -> Decimal:
    statement = select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
        PaymentTransaction.direction == direction
    )
    if sale_id is not None:
        statement = statement.where(PaymentTransaction.sale_id == sale_id)
    else:
        statement = statement.where(PaymentTransaction.sale_return_id == sale_return_id)
    return Decimal(session.scalar(statement) or 0)


def record_sale_payment(
    session: Session,
    *,
    company_id: UUID,
    sale_id: UUID,
    payment_method: str,
    amount: Decimal,
    reference_no: str | None = None,
    note: str | None = None,
) -> PaymentTransaction:
    """Record a partial or full collection/payment against a completed sale."""
    _validate_amount(amount)
    _validate_method(payment_method)
    sale = session.execute(
        select(Sale).where(
            Sale.id == sale_id, Sale.company_id == company_id
        ).with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    if sale.status != "COMPLETED":
        raise ValueError("只有已完成的銷售單可以收付款。")

    obligation = sale.final_amount
    if obligation == 0:
        raise ValueError("此銷售單金額為零，無需建立收付款紀錄。")
    direction = "IN" if obligation > 0 else "OUT"
    assert_business_day_open(
        session, site_id=sale.site_id, at=datetime.now(timezone.utc)
    )
    existing = _existing_amount(session, sale_id=sale.id, direction=direction)
    remaining = abs(obligation) - existing
    if amount > remaining:
        raise ValueError(f"收付款金額超過未結清餘額，目前尚可登錄：{remaining}。")

    transaction = PaymentTransaction(
        company_id=company_id,
        site_id=sale.site_id,
        sale_id=sale.id,
        direction=direction,
        payment_method=payment_method,
        amount=amount,
        currency_code=sale.currency_code,
        reference_no=reference_no,
        paid_at=datetime.now(timezone.utc),
        note=note,
    )
    session.add(transaction)
    session.flush()
    return transaction


def record_return_payment(
    session: Session,
    *,
    company_id: UUID,
    return_id: UUID,
    payment_method: str,
    amount: Decimal,
    reference_no: str | None = None,
    note: str | None = None,
) -> PaymentTransaction:
    """Record the actual refund or customer collection for a return obligation."""
    _validate_amount(amount)
    _validate_method(payment_method)
    returned = session.execute(
        select(SaleReturn).where(
            SaleReturn.id == return_id,
            SaleReturn.company_id == company_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if returned is None:
        raise ValueError("找不到指定退貨單。")
    obligation = returned.settlement_reversal_amount
    if obligation == 0:
        raise ValueError("此退貨單結算金額為零，無需建立收付款紀錄。")
    direction = "IN" if obligation > 0 else "OUT"
    assert_business_day_open(
        session, site_id=returned.site_id, at=datetime.now(timezone.utc)
    )
    existing = _existing_amount(
        session, sale_return_id=returned.id, direction=direction
    )
    remaining = abs(obligation) - existing
    if amount > remaining:
        raise ValueError(f"收付款金額超過未結清餘額，目前尚可登錄：{remaining}。")

    transaction = PaymentTransaction(
        company_id=company_id,
        site_id=returned.site_id,
        sale_return_id=returned.id,
        direction=direction,
        payment_method=payment_method,
        amount=amount,
        currency_code=returned.currency_code,
        reference_no=reference_no,
        paid_at=datetime.now(timezone.utc),
        note=note,
    )
    session.add(transaction)
    session.flush()
    return transaction
