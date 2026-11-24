"""Append-only customer collection and refund transaction services."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.payment_transaction import PaymentTransaction
from app.models.customer_order import CustomerOrder
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.services.daily_closing import assert_business_day_open

PAYMENT_METHODS = {"CASH", "CARD", "TRANSFER", "OTHER"}
CENT = Decimal("0.01")


class CustomerOrderPaymentIdempotencyConflict(ValueError):
    """Raised when a retry key is reused for a different customer-order payment."""


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

    # A mixed sale has a fixed tender plan: card principal plus its 5% fee
    # must be collected by card, and the remaining principal must be cash.
    # Do not let the general outstanding balance mask a wrong tender split.
    if direction == "IN" and sale.payment_method == "MIXED":
        if payment_method not in {"CARD", "CASH"}:
            raise ValueError("部分刷卡銷售只能使用刷卡及現金收款。")
        from app.services.pricing.rounding import round_twd_like_legacy

        method_existing = Decimal(session.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                PaymentTransaction.sale_id == sale.id,
                PaymentTransaction.direction == "IN",
                PaymentTransaction.payment_method == payment_method,
            )
        ) or 0)
        if payment_method == "CARD":
            tender_limit = sale.card_amount + sale.card_fee
        else:
            tender_limit = max(
                Decimal("0"),
                round_twd_like_legacy(sale.subtotal) - sale.card_amount,
            )
        method_remaining = tender_limit - method_existing
        if amount > method_remaining:
            label = "刷卡（含 5% 手續費）" if payment_method == "CARD" else "現金"
            raise ValueError(
                f"{label}收款超過此付款方式應收餘額，目前尚可登錄：{method_remaining}。"
            )

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




def refund_customer_order_payment(
    session: Session,
    *,
    company_id: UUID,
    order_id: UUID,
    payment_method: str,
    amount: Decimal,
    note: str | None = None,
    idempotency_key: UUID | None = None,
) -> PaymentTransaction:
    """Append a customer refund and reduce the net amount held for an order."""
    _validate_amount(amount)
    _validate_method(payment_method)
    idempotency_reference = f"CO-REFUND:{idempotency_key}" if idempotency_key else None
    if idempotency_key is not None:
        company = session.scalar(
            select(Company).where(Company.id == company_id).with_for_update()
        )
        if company is None:
            raise ValueError("找不到指定公司。")
    order = session.execute(
        select(CustomerOrder).where(
            CustomerOrder.id == order_id,
            CustomerOrder.company_id == company_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ValueError("找不到指定客訂單。")
    if idempotency_reference:
        existing = session.scalar(select(PaymentTransaction).where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.reference_no == idempotency_reference,
        ))
        if existing is not None:
            if (
                existing.customer_order_id != order.id
                or existing.direction != "OUT"
                or existing.payment_method != payment_method
                or existing.amount != amount
                or existing.currency_code != order.currency_code
                or existing.note != note
            ):
                raise CustomerOrderPaymentIdempotencyConflict(
                    "此退款識別碼已用於不同的退款內容，請確認原退款紀錄。"
                )
            return existing
    if order.status in {"COMPLETED", "CANCELLED"}:
        raise ValueError("已完成或已取消的客訂單不可退款。")
    if amount > order.deposit_amount:
        raise ValueError(f"退款金額不可超過目前已收訂金／款項：{order.deposit_amount}。")
    assert_business_day_open(
        session, site_id=order.site_id, at=datetime.now(timezone.utc)
    )
    transaction = PaymentTransaction(
        company_id=company_id,
        site_id=order.site_id,
        customer_order_id=order.id,
        direction="OUT",
        payment_method=payment_method,
        amount=amount,
        currency_code=order.currency_code,
        reference_no=idempotency_reference,
        paid_at=datetime.now(timezone.utc),
        note=note or "客訂訂金退款",
    )
    order.deposit_amount -= amount
    session.add(transaction)
    session.flush()
    return transaction


def record_customer_order_payment(
    session: Session,
    *,
    company_id: UUID,
    order_id: UUID,
    payment_method: str,
    amount: Decimal,
    note: str | None = None,
    idempotency_key: UUID | None = None,
    idempotency_prefix: str = "CO-PAYMENT",
) -> PaymentTransaction:
    """Record a deposit or balance collection against a customer special order."""
    _validate_amount(amount)
    _validate_method(payment_method)
    if idempotency_prefix not in {"CO-PAYMENT", "CO-CREATE"}:
        raise ValueError("不支援的客訂付款識別碼類型。")
    idempotency_reference = (
        f"{idempotency_prefix}:{idempotency_key}"
        if idempotency_key is not None else None
    )
    if idempotency_key is not None:
        company = session.scalar(
            select(Company).where(Company.id == company_id).with_for_update()
        )
        if company is None:
            raise ValueError("找不到指定公司。")
    order = session.execute(
        select(CustomerOrder).where(
            CustomerOrder.id == order_id,
            CustomerOrder.company_id == company_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ValueError("找不到指定客訂單。")
    if idempotency_reference is not None:
        existing = session.scalar(select(PaymentTransaction).where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.reference_no == idempotency_reference,
        ))
        if existing is not None:
            matches = (
                existing.customer_order_id == order.id
                and existing.direction == "IN"
                and existing.payment_method == payment_method
                and existing.amount == amount
                and existing.currency_code == order.currency_code
                and existing.note == note
            )
            if not matches:
                raise CustomerOrderPaymentIdempotencyConflict(
                    "此付款識別碼已用於不同的客訂收款內容，請確認原付款紀錄後再操作。"
                )
            return existing
    if order.status in {"COMPLETED", "CANCELLED"}:
        raise ValueError("已完成或已取消的訂單不可再收款。")
    remaining = order.total_amount - order.deposit_amount
    if amount > remaining:
        raise ValueError(f"收款金額超過訂單未收餘額，目前尚可收取：{remaining}。")
    assert_business_day_open(
        session, site_id=order.site_id, at=datetime.now(timezone.utc)
    )
    order.deposit_amount += amount
    transaction = PaymentTransaction(
        company_id=company_id,
        site_id=order.site_id,
        customer_order_id=order.id,
        direction="IN",
        payment_method=payment_method,
        amount=amount,
        currency_code=order.currency_code,
        reference_no=idempotency_reference,
        paid_at=datetime.now(timezone.utc),
        note=note,
    )
    session.add(transaction)
    session.flush()
    return transaction
