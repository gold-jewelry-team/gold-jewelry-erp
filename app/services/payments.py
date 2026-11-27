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
from app.services.pricing.rounding import round_twd_like_legacy

PAYMENT_METHODS = {"CASH", "CARD", "TRANSFER", "OTHER"}
CENT = Decimal("0.01")


class CustomerOrderPaymentIdempotencyConflict(ValueError):
    """Raised when a retry key is reused for a different customer-order payment."""


class PaymentIdempotencyConflict(ValueError):
    """Raised when a sale/return payment retry key is reused with different details."""




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


def _existing_idempotent_payment(
    session: Session,
    *,
    company_id: UUID,
    idempotency_key: UUID | None,
    source_field: str,
    source_id: UUID,
    direction: str,
    payment_method: str,
    amount: Decimal,
    currency_code: str,
    reference_no: str | None,
    note: str | None,
) -> PaymentTransaction | None:
    if idempotency_key is None:
        return None
    existing = session.scalar(
        select(PaymentTransaction)
        .where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if existing is None:
        return None
    same_request = (
        getattr(existing, source_field) == source_id
        and existing.direction == direction
        and existing.payment_method == payment_method
        and existing.amount == amount
        and existing.currency_code == currency_code
        and existing.reference_no == reference_no
        and existing.note == note
    )
    if not same_request:
        raise PaymentIdempotencyConflict(
            "此收付款識別碼已用於不同交易內容，請先查閱原收付款紀錄。"
        )
    return existing


def record_sale_payment(
    session: Session,
    *,
    company_id: UUID,
    sale_id: UUID,
    payment_method: str,
    amount: Decimal,
    reference_no: str | None = None,
    note: str | None = None,
    idempotency_key: UUID | None = None,
    return_created: bool = False,
) -> PaymentTransaction | tuple[PaymentTransaction, bool]:
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
    if sale.customer_order_id is not None and direction == "IN":
        raise ValueError("此銷售單已連結客訂，客訂款項必須統一登錄在客訂收付款流水，避免重複入帳。")
    existing = _existing_idempotent_payment(
        session, company_id=company_id, idempotency_key=idempotency_key,
        source_field="sale_id", source_id=sale.id, direction=direction,
        payment_method=payment_method, amount=amount, currency_code=sale.currency_code,
        reference_no=reference_no, note=note,
    )
    if existing is not None:
        return (existing, False) if return_created else existing

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
        idempotency_key=idempotency_key,
        paid_at=datetime.now(timezone.utc),
        note=note,
    )
    session.add(transaction)
    session.flush()
    return (transaction, True) if return_created else transaction


def record_return_payment(
    session: Session,
    *,
    company_id: UUID,
    return_id: UUID,
    payment_method: str,
    amount: Decimal,
    reference_no: str | None = None,
    note: str | None = None,
    idempotency_key: UUID | None = None,
    return_created: bool = False,
) -> PaymentTransaction | tuple[PaymentTransaction, bool]:
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
    existing = _existing_idempotent_payment(
        session, company_id=company_id, idempotency_key=idempotency_key,
        source_field="sale_return_id", source_id=returned.id, direction=direction,
        payment_method=payment_method, amount=amount, currency_code=returned.currency_code,
        reference_no=reference_no, note=note,
    )
    if existing is not None:
        return (existing, False) if return_created else existing

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
        idempotency_key=idempotency_key,
        paid_at=datetime.now(timezone.utc),
        note=note,
    )
    session.add(transaction)
    session.flush()
    return (transaction, True) if return_created else transaction




def _customer_order_payment_method_net(
    session: Session, order_id: UUID, payment_method: str,
) -> Decimal:
    rows = session.execute(
        select(
            PaymentTransaction.direction,
            func.coalesce(func.sum(PaymentTransaction.amount), 0),
        )
        .where(
            PaymentTransaction.customer_order_id == order_id,
            PaymentTransaction.payment_method == payment_method,
        )
        .group_by(PaymentTransaction.direction)
    ).all()
    return sum(
        (Decimal(amount or 0) if direction == "IN" else -Decimal(amount or 0) for direction, amount in rows),
        Decimal("0"),
    )


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
    linked_sale = session.execute(
        select(Sale).where(Sale.customer_order_id == order.id).with_for_update()
    ).scalar_one_or_none()
    refundable_balance = order.deposit_amount
    if linked_sale is not None:
        if linked_sale.status != "DRAFT":
            raise ValueError("客訂已連結非草稿銷售，不能再修改訂金退款；請先核對正式銷售狀態。")
        retained_amount = max(Decimal("0"), linked_sale.final_amount)
        refundable_balance = max(Decimal("0"), order.deposit_amount - retained_amount)
    if amount > refundable_balance:
        raise ValueError(f"退款金額超過客訂可退餘額，目前最多可退：{refundable_balance}。")
    method_net = _customer_order_payment_method_net(session, order.id, payment_method)
    method_refundable = method_net
    if linked_sale is not None:
        method_nets = {
            method: _customer_order_payment_method_net(session, order.id, method)
            for method in ("CASH", "CARD", "TRANSFER", "OTHER")
        }
        if payment_method == "CARD":
            allowed_card = linked_sale.card_amount + linked_sale.card_fee
            method_refundable = min(method_net, max(Decimal("0"), method_nets["CARD"] - allowed_card))
        else:
            allowed_noncard = max(
                Decimal("0"),
                round_twd_like_legacy(linked_sale.subtotal) - linked_sale.card_amount,
            )
            received_noncard = sum(
                (value for method, value in method_nets.items() if method != "CARD"),
                Decimal("0"),
            )
            method_refundable = min(method_net, max(Decimal("0"), received_noncard - allowed_noncard))
    if amount > method_refundable:
        raise ValueError(f"退款金額不可超過此付款方式的可退超收餘額，目前可退：{method_refundable}。")
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
    linked_sale = session.execute(
        select(Sale).where(Sale.customer_order_id == order.id).with_for_update()
    ).scalar_one_or_none()
    if linked_sale is not None:
        if linked_sale.status != "DRAFT":
            raise ValueError("客訂已連結非草稿銷售，不能再新增客訂收款。")
        obligation = max(Decimal("0"), linked_sale.final_amount)
        remaining = max(Decimal("0"), obligation - order.deposit_amount)
        if amount > remaining:
            raise ValueError(f"正式銷售尚可收款餘額為：{remaining}。")
        method_nets = {
            method: _customer_order_payment_method_net(session, order.id, method)
            for method in ("CASH", "CARD", "TRANSFER", "OTHER")
        }
        if payment_method == "CARD":
            method_limit = linked_sale.card_amount + linked_sale.card_fee
            already_collected = method_nets.get("CARD", Decimal("0"))
        else:
            method_limit = max(
                Decimal("0"),
                round_twd_like_legacy(linked_sale.subtotal) - linked_sale.card_amount,
            )
            already_collected = sum(
                (value for method, value in method_nets.items() if method != "CARD"),
                Decimal("0"),
            )
        method_remaining = method_limit - already_collected
        if amount > method_remaining:
            raise ValueError(
                f"此付款方式超過正式銷售可收餘額，目前最多可收：{max(Decimal('0'), method_remaining)}。"
            )
    else:
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
