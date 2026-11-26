"""Supplier bill creation and allocated payable settlement."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.purchase import Purchase
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import (
    SupplierBill, SupplierPayment, SupplierPaymentAllocation,
    SupplierPaymentReversal, SupplierPaymentReversalAllocation,
)
from app.models.gold_material import GoldMaterialSettlementAllocation
from app.services.daily_closing import assert_business_day_open

CENT = Decimal("0.01")
PAYMENT_METHODS = {"CASH", "CARD", "TRANSFER", "OTHER"}


def _validate_money(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or value <= 0:
        raise ValueError(f"{label}必須是正數 Decimal。")
    if value.quantize(CENT) != value:
        raise ValueError(f"{label}最多只能有小數點後兩位。")


class SupplierBillIdempotencyConflict(ValueError):
    """Raised when a supplier bill number is reused for different details."""


def create_supplier_bill(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    supplier_id: UUID,
    bill_no: str,
    bill_date: date,
    due_date: date | None,
    currency_code: str,
    total_amount: Decimal,
    purchase_id: UUID | None = None,
    note: str | None = None,
    return_created: bool = False,
) -> SupplierBill | tuple[SupplierBill, bool]:
    _validate_money(total_amount, "供應商帳單金額")
    if due_date is not None and due_date < bill_date:
        raise ValueError("到期日不可早於帳單日期。")
    if len(currency_code) != 3 or not currency_code.isalpha():
        raise ValueError("幣別必須使用三碼英文字母代碼。")

    site = session.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")

    # Serialize bill creation per supplier. The unique identity is
    # (company_id, supplier_id, bill_no), so locking the supplier rather
    # than a site also covers the same supplier invoicing multiple sites.
    supplier = session.execute(
        select(Supplier)
        .where(Supplier.id == supplier_id, Supplier.company_id == company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if supplier is None:
        raise ValueError("供應商不存在或不屬於指定公司。")

    normalized_currency = currency_code.upper()
    existing = session.scalar(
        select(SupplierBill)
        .where(
            SupplierBill.company_id == company_id,
            SupplierBill.supplier_id == supplier_id,
            SupplierBill.bill_no == bill_no,
        )
        .with_for_update()
    )
    if existing is not None:
        same_request = (
            existing.site_id == site_id
            and existing.purchase_id == purchase_id
            and existing.bill_date == bill_date
            and existing.due_date == due_date
            and existing.currency_code == normalized_currency
            and existing.total_amount == total_amount
            and existing.note == note
        )
        if not same_request:
            raise SupplierBillIdempotencyConflict(
                "此供應商帳單號碼重複，但本次內容與原帳單不同；請查閱原帳單，勿重複建立。"
            )
        return (existing, False) if return_created else existing

    if purchase_id is not None:
        purchase = session.get(Purchase, purchase_id)
        if (
            purchase is None
            or purchase.company_id != company_id
            or purchase.site_id != site_id
            or purchase.supplier_id != supplier_id
            or purchase.status not in {"ORDERED", "PARTIALLY_RECEIVED", "RECEIVED"}
        ):
            raise ValueError("關聯採購單不存在、供應商／據點不符，或採購單狀態不允許建立應付帳單。")
        if purchase.currency_code != normalized_currency:
            raise ValueError("帳單幣別必須與關聯採購單一致。")

    bill = SupplierBill(
        company_id=company_id,
        site_id=site_id,
        supplier_id=supplier_id,
        purchase_id=purchase_id,
        bill_no=bill_no,
        bill_date=bill_date,
        due_date=due_date,
        currency_code=normalized_currency,
        total_amount=total_amount,
        status="OPEN",
        note=note,
    )
    session.add(bill)
    session.flush()
    return (bill, True) if return_created else bill


class SupplierPaymentIdempotencyConflict(ValueError):
    """Raised when a supplier payment number is reused for different details."""


def record_supplier_payment(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    supplier_id: UUID,
    payment_no: str,
    payment_method: str,
    allocations: list[dict],
    reference_no: str | None = None,
    note: str | None = None,
    return_created: bool = False,
) -> SupplierPayment | tuple[SupplierPayment, bool]:
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("不支援的供應商付款方式。")
    if not allocations:
        raise ValueError("供應商付款至少需要一筆帳單分攤。")
    bill_ids = [item["bill_id"] for item in allocations]
    if len(bill_ids) != len(set(bill_ids)):
        raise ValueError("同一付款單不可重複指定同一張供應商帳單。")

    allocation_amounts = {}
    for item in allocations:
        amount = item["amount"]
        _validate_money(amount, "分攤金額")
        allocation_amounts[item["bill_id"]] = amount
    total_amount = sum(allocation_amounts.values(), Decimal("0"))

    # Lock the site before checking the unique (site_id, payment_no) identity.
    # This serializes concurrent retries even when the first response is lost.
    site = session.execute(
        select(Site).where(Site.id == site_id).with_for_update()
    ).scalar_one_or_none()
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")

    existing = session.scalar(select(SupplierPayment).where(
        SupplierPayment.site_id == site_id,
        SupplierPayment.payment_no == payment_no,
    ))
    if existing is not None:
        existing_allocations = {
            row.bill_id: row.amount
            for row in session.scalars(
                select(SupplierPaymentAllocation).where(
                    SupplierPaymentAllocation.payment_id == existing.id
                )
            ).all()
        }
        same_request = (
            existing.company_id == company_id
            and existing.supplier_id == supplier_id
            and existing.payment_method == payment_method
            and existing.total_amount == total_amount
            and existing.currency_code == "TWD"
            and existing.reference_no == reference_no
            and existing.note == note
            and existing_allocations == allocation_amounts
        )
        if not same_request:
            raise SupplierPaymentIdempotencyConflict(
                "此供應商付款單號已用於不同的付款內容；請查閱原付款紀錄，勿以新單號重複付款。"
            )
        return (existing, False) if return_created else existing

    bills = list(session.scalars(
        select(SupplierBill)
        .where(SupplierBill.id.in_(bill_ids))
        .order_by(SupplierBill.id)
        .with_for_update()
    ).all())
    if len(bills) != len(bill_ids):
        raise ValueError("部分供應商帳單不存在。")

    for bill in bills:
        if (
            bill.company_id != company_id
            or bill.site_id != site_id
            or bill.supplier_id != supplier_id
        ):
            raise ValueError("付款分攤帳單必須屬於相同公司、據點及供應商。")
        if bill.status == "VOID":
            raise ValueError("已作廢的供應商帳單不可付款。")
    currencies = {bill.currency_code for bill in bills}
    if len(currencies) != 1:
        raise ValueError("同一筆供應商付款不可混合不同幣別。")
    if currencies != {"TWD"}:
        raise ValueError("目前每日結帳僅支援新台幣付款；外幣帳單可建檔，但須待多幣別付款與匯率模組上線後才能付款。")

    paid_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=site_id, at=paid_at)

    remaining_by_bill = {}
    for bill in bills:
        cash_paid = Decimal(session.scalar(
            select(func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0))
            .where(SupplierPaymentAllocation.bill_id == bill.id)
        ) or 0)
        cash_reversed = Decimal(session.scalar(
            select(func.coalesce(func.sum(SupplierPaymentReversalAllocation.amount), 0))
            .join(
                SupplierPaymentAllocation,
                SupplierPaymentAllocation.id
                == SupplierPaymentReversalAllocation.payment_allocation_id,
            )
            .where(SupplierPaymentAllocation.bill_id == bill.id)
        ) or 0)
        gold_paid = Decimal(session.scalar(
            select(func.coalesce(func.sum(GoldMaterialSettlementAllocation.amount), 0))
            .where(GoldMaterialSettlementAllocation.bill_id == bill.id)
        ) or 0)
        already_paid = cash_paid - cash_reversed + gold_paid
        remaining = bill.total_amount - already_paid
        requested = allocation_amounts[bill.id]
        if requested > remaining:
            raise ValueError(f"帳單 {bill.bill_no} 分攤金額超過未付餘額，目前尚欠：{remaining}。")
        remaining_by_bill[bill.id] = already_paid + requested

    payment = SupplierPayment(
        company_id=company_id,
        site_id=site_id,
        supplier_id=supplier_id,
        payment_no=payment_no,
        payment_method=payment_method,
        total_amount=total_amount,
        currency_code=next(iter(currencies)),
        reference_no=reference_no,
        paid_at=paid_at,
        note=note,
    )
    session.add(payment)
    session.flush()

    for bill in bills:
        session.add(SupplierPaymentAllocation(
            payment_id=payment.id,
            bill_id=bill.id,
            amount=allocation_amounts[bill.id],
        ))
        paid = remaining_by_bill[bill.id]
        bill.status = "PAID" if paid == bill.total_amount else "PARTIALLY_PAID"

    session.flush()
    return (payment, True) if return_created else payment



class SupplierPaymentReversalIdempotencyConflict(ValueError):
    """Raised when a reversal number is reused for a different reversal."""


def record_supplier_payment_reversal(
    session: Session,
    *,
    company_id: UUID,
    payment_id: UUID,
    reversal_no: str,
    allocations: list[dict],
    reason: str,
    return_created: bool = False,
) -> SupplierPaymentReversal | tuple[SupplierPaymentReversal, bool]:
    """Append a partial/full reversal against exact original payment allocations."""
    memo = (reason or "").strip()
    number = (reversal_no or "").strip()
    if not memo:
        raise ValueError("沖銷原因不可空白。")
    if not number:
        raise ValueError("沖銷單號不可空白。")
    if not allocations:
        raise ValueError("供應商付款沖銷至少需要一筆原付款分攤。")

    requested: dict[UUID, Decimal] = {}
    for item in allocations:
        allocation_id = item["payment_allocation_id"]
        amount = item["amount"]
        _validate_money(amount, "沖銷金額")
        if allocation_id in requested:
            raise ValueError("同一張原付款分攤不可在同一沖銷單中重複指定。")
        requested[allocation_id] = amount
    reversal_total = sum(requested.values(), Decimal("0"))

    preliminary = session.scalar(select(SupplierPayment).where(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == company_id,
    ))
    if preliminary is None:
        raise ValueError("找不到指定供應商付款紀錄。")

    # Lock the site first, matching supplier payment creation. This serializes
    # duplicate reversal requests and competing balance adjustments.
    site = session.execute(select(Site).where(
        Site.id == preliminary.site_id,
        Site.company_id == company_id,
    ).with_for_update()).scalar_one_or_none()
    if site is None:
        raise ValueError("供應商付款據點不存在或不屬於指定公司。")

    existing = session.scalar(select(SupplierPaymentReversal).where(
        SupplierPaymentReversal.site_id == site.id,
        SupplierPaymentReversal.reversal_no == number,
    ).with_for_update())
    if existing is not None:
        existing_allocations = {
            row.payment_allocation_id: row.amount
            for row in session.scalars(select(SupplierPaymentReversalAllocation).where(
                SupplierPaymentReversalAllocation.reversal_id == existing.id
            )).all()
        }
        if (
            existing.company_id != company_id
            or existing.payment_id != payment_id
            or existing.total_amount != reversal_total
            or existing.reason != memo
            or existing_allocations != requested
        ):
            raise SupplierPaymentReversalIdempotencyConflict(
                "此沖銷單號已用於不同的供應商付款沖銷內容，請先查閱原沖銷紀錄。"
            )
        return (existing, False) if return_created else existing

    payment = session.execute(select(SupplierPayment).where(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == company_id,
    ).with_for_update()).scalar_one_or_none()
    if payment is None:
        raise ValueError("找不到指定供應商付款紀錄。")
    if payment.currency_code != "TWD":
        raise ValueError("目前只支援新台幣供應商付款沖銷。")

    now = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=payment.site_id, at=now)

    original_allocations = list(session.scalars(select(SupplierPaymentAllocation)
        .where(SupplierPaymentAllocation.payment_id == payment.id)
        .order_by(SupplierPaymentAllocation.id)
        .with_for_update()).all())
    original_by_id = {row.id: row for row in original_allocations}
    if not set(requested).issubset(original_by_id):
        raise ValueError("沖銷分攤只能指定這筆原付款實際存在的帳單分攤。")

    previous = list(session.scalars(select(SupplierPaymentReversalAllocation)
        .where(SupplierPaymentReversalAllocation.payment_allocation_id.in_(list(requested)))
        .with_for_update()).all())
    reversed_by_allocation: dict[UUID, Decimal] = {}
    for row in previous:
        reversed_by_allocation[row.payment_allocation_id] = (
            reversed_by_allocation.get(row.payment_allocation_id, Decimal("0")) + row.amount
        )
    for allocation_id, amount in requested.items():
        remaining = original_by_id[allocation_id].amount - reversed_by_allocation.get(
            allocation_id, Decimal("0")
        )
        if amount > remaining:
            raise ValueError(f"原付款分攤尚可沖銷金額為 {remaining}，本次不可超額沖銷。")

    bill_ids = sorted({original_by_id[key].bill_id for key in requested}, key=str)
    bills = list(session.scalars(select(SupplierBill)
        .where(SupplierBill.id.in_(bill_ids))
        .order_by(SupplierBill.id)
        .with_for_update()).all())
    if len(bills) != len(bill_ids):
        raise ValueError("原付款分攤關聯的供應商帳單不存在。")
    if any(
        bill.company_id != company_id
        or bill.site_id != payment.site_id
        or bill.supplier_id != payment.supplier_id
        for bill in bills
    ):
        raise ValueError("原付款分攤的帳單公司、據點或供應商不一致。")

    reversal = SupplierPaymentReversal(
        company_id=company_id,
        site_id=payment.site_id,
        supplier_id=payment.supplier_id,
        payment_id=payment.id,
        reversal_no=number,
        total_amount=reversal_total,
        currency_code=payment.currency_code,
        reversed_at=now,
        reason=memo,
    )
    session.add(reversal)
    session.flush()
    for allocation_id, amount in requested.items():
        session.add(SupplierPaymentReversalAllocation(
            reversal_id=reversal.id,
            payment_allocation_id=allocation_id,
            amount=amount,
        ))
    session.flush()

    for bill in bills:
        cash_paid = Decimal(session.scalar(select(func.coalesce(
            func.sum(SupplierPaymentAllocation.amount), 0
        )).where(SupplierPaymentAllocation.bill_id == bill.id)) or 0)
        cash_reversed = Decimal(session.scalar(select(func.coalesce(
            func.sum(SupplierPaymentReversalAllocation.amount), 0
        )).join(
            SupplierPaymentAllocation,
            SupplierPaymentAllocation.id
            == SupplierPaymentReversalAllocation.payment_allocation_id,
        ).where(SupplierPaymentAllocation.bill_id == bill.id)) or 0)
        gold_paid = Decimal(session.scalar(select(func.coalesce(
            func.sum(GoldMaterialSettlementAllocation.amount), 0
        )).where(GoldMaterialSettlementAllocation.bill_id == bill.id)) or 0)
        net_paid = cash_paid - cash_reversed + gold_paid
        bill.status = (
            "PAID" if net_paid == bill.total_amount
            else "PARTIALLY_PAID" if net_paid > 0
            else "OPEN"
        )

    session.flush()
    return (reversal, True) if return_created else reversal
