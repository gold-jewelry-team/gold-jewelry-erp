"""Fine-gold inventory ledger and supplier old-gold settlement."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.gold_material import GoldMaterialMovement, GoldMaterialSettlementAllocation
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.purchase import Purchase
from app.models.supplier_payable import SupplierBill, SupplierPaymentAllocation
from app.services.daily_closing import assert_business_day_open

WEIGHT_GRAMS = {"G": Decimal("1"), "QIAN": Decimal("3.75"), "LIANG": Decimal("37.5")}
INCOMING_TYPES = {"OPENING", "RECEIPT", "ADJUSTMENT_IN"}
OUTGOING_TYPES = {"ADJUSTMENT_OUT", "SUPPLIER_DELIVERY"}
CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


def _money(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or value < 0 or value.quantize(CENT) != value:
        raise ValueError(f"{label}必須是非負且最多小數點後兩位。")


def _balance(session: Session, *, company_id: UUID, site_id: UUID) -> Decimal:
    signed_weight = case(
        (GoldMaterialMovement.movement_type.in_(INCOMING_TYPES), GoldMaterialMovement.fine_gold_weight_g),
        else_=-GoldMaterialMovement.fine_gold_weight_g,
    )
    return Decimal(session.scalar(
        select(func.coalesce(func.sum(signed_weight), 0)).where(
            GoldMaterialMovement.company_id == company_id,
            GoldMaterialMovement.site_id == site_id,
        )
    ) or 0)


class GoldMaterialMovementIdempotencyConflict(ValueError):
    """Raised when a movement number is reused for different details."""


def record_gold_material_movement(
    session: Session, *, company_id: UUID, site_id: UUID,
    movement_no: str, movement_type: str, purity_label: str,
    purity_ratio: Decimal, gross_weight: Decimal, loss_weight: Decimal,
    weight_unit_code: str, gold_price_value: Decimal, gold_price_unit_code: str,
    deduction_amount: Decimal, supplier_id: UUID | None = None,
    purchase_id: UUID | None = None, source_type: str | None = None,
    allocations: list[dict] | None = None, note: str | None = None,
    return_created: bool = False,
) -> GoldMaterialMovement | tuple[GoldMaterialMovement, bool]:
    if movement_type not in INCOMING_TYPES | OUTGOING_TYPES:
        raise ValueError("不支援的金料異動類型。")
    if weight_unit_code not in WEIGHT_GRAMS or gold_price_unit_code not in WEIGHT_GRAMS:
        raise ValueError("重量及金價單位僅支援公克、錢、兩。")
    if not isinstance(purity_ratio, Decimal) or purity_ratio <= 0 or purity_ratio > 1:
        raise ValueError("成色比例必須大於 0 且不得超過 1。")
    if not isinstance(gross_weight, Decimal) or gross_weight <= 0:
        raise ValueError("舊金毛重必須是正數。")
    if not isinstance(loss_weight, Decimal) or loss_weight < 0 or loss_weight >= gross_weight:
        raise ValueError("耗損重量不可小於 0，也不可大於或等於毛重。")
    if not isinstance(gold_price_value, Decimal) or gold_price_value <= 0:
        raise ValueError("估價金價必須是正數。")
    _money(deduction_amount, "折減／處理費")

    normalized_movement_no = movement_no.strip()
    if not normalized_movement_no:
        raise ValueError("金料異動單號不可空白。")
    normalized_purity_label = purity_label.strip()
    if not normalized_purity_label:
        raise ValueError("成色標示不可空白。")
    normalized_source_type = (source_type or "").strip() or None

    site = session.execute(
        select(Site).where(Site.id == site_id, Site.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if site is None:
        raise ValueError("據點不存在或不屬於指定公司。")

    # Calculate the exact values before looking up an existing movement. A retry
    # must return the original row even when its bill is now fully paid or the
    # business day has since been closed.
    net_weight = (gross_weight - loss_weight).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    fine_gold_weight_g = (
        net_weight * WEIGHT_GRAMS[weight_unit_code] * purity_ratio
    ).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    gross_value = (
        fine_gold_weight_g / WEIGHT_GRAMS[gold_price_unit_code] * gold_price_value
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    valuation_amount = (gross_value - deduction_amount).quantize(CENT, rounding=ROUND_HALF_UP)
    if valuation_amount <= 0:
        raise ValueError("扣除折減／處理費後的舊金價值必須大於 0。")

    normalized_allocations = allocations or []
    allocation_amounts: dict[UUID, Decimal] = {}
    if movement_type == "SUPPLIER_DELIVERY":
        if not normalized_allocations:
            raise ValueError("供應商舊金折抵必須分攤至至少一張供應商帳單。")
        for item in normalized_allocations:
            bill_id = item["bill_id"]
            amount = item["amount"]
            if bill_id in allocation_amounts:
                raise ValueError("同一筆舊金交付不可重複指定同一張供應商帳單。")
            if not isinstance(amount, Decimal) or amount <= 0 or amount.quantize(CENT) != amount:
                raise ValueError("舊金折抵分攤金額必須是正數，且最多小數點後兩位。")
            allocation_amounts[bill_id] = amount
        allocation_total = sum(allocation_amounts.values(), Decimal("0"))
        if allocation_total != valuation_amount:
            raise ValueError("舊金折抵分攤合計必須等於本次舊金估值金額。")
    elif normalized_allocations:
        raise ValueError("只有交付供應商折抵時才能指定帳單分攤。")

    existing = session.execute(
        select(GoldMaterialMovement).where(
            GoldMaterialMovement.company_id == company_id,
            GoldMaterialMovement.site_id == site_id,
            GoldMaterialMovement.movement_no == normalized_movement_no,
        ).with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        # When the supplier is inferred from a linked purchase, preserve the
        # original effective supplier on exact retries.
        effective_supplier_id = supplier_id
        if effective_supplier_id is None and existing.purchase_id == purchase_id:
            effective_supplier_id = existing.supplier_id
        existing_allocations = {
            row.bill_id: row.amount
            for row in session.scalars(
                select(GoldMaterialSettlementAllocation).where(
                    GoldMaterialSettlementAllocation.movement_id == existing.id
                )
            ).all()
        }
        same_request = (
            existing.company_id == company_id
            and existing.site_id == site_id
            and existing.supplier_id == effective_supplier_id
            and existing.purchase_id == purchase_id
            and existing.movement_no == normalized_movement_no
            and existing.movement_type == movement_type
            and existing.source_type == normalized_source_type
            and existing.purity_label == normalized_purity_label
            and existing.purity_ratio == purity_ratio
            and existing.gross_weight == gross_weight
            and existing.loss_weight == loss_weight
            and existing.net_weight == net_weight
            and existing.weight_unit_code == weight_unit_code
            and existing.fine_gold_weight_g == fine_gold_weight_g
            and existing.gold_price_value == gold_price_value
            and existing.gold_price_unit_code == gold_price_unit_code
            and existing.deduction_amount == deduction_amount
            and existing.valuation_amount == valuation_amount
            and existing.note == note
            and existing_allocations == allocation_amounts
        )
        if not same_request:
            raise GoldMaterialMovementIdempotencyConflict(
                "此金料異動單號已用於不同內容；請先核對原異動紀錄，不可用相同單號建立新異動。"
            )
        return (existing, False) if return_created else existing

    assert_business_day_open(session, site_id=site_id, at=datetime.now(timezone.utc))

    supplier = None
    if supplier_id is not None:
        supplier = session.get(Supplier, supplier_id)
        if supplier is None or supplier.company_id != company_id or not supplier.is_active:
            raise ValueError("供應商不存在、未啟用或不屬於指定公司。")

    purchase = None
    if purchase_id is not None:
        purchase = session.get(Purchase, purchase_id)
        if (
            purchase is None or purchase.company_id != company_id
            or purchase.site_id != site_id
            or (supplier_id is not None and purchase.supplier_id != supplier_id)
            or purchase.status not in {"ORDERED", "PARTIALLY_RECEIVED", "RECEIVED"}
        ):
            raise ValueError("關聯採購單不存在、供應商／據點不符，或狀態不允許折抵。")
        if supplier_id is None:
            supplier_id = purchase.supplier_id
            supplier = session.get(Supplier, supplier_id)
            if supplier is None or supplier.company_id != company_id or not supplier.is_active:
                raise ValueError("採購單供應商不存在、未啟用或不屬於指定公司。")

    bills = []
    paid_by_bill = {}
    if movement_type == "SUPPLIER_DELIVERY":
        if supplier is None:
            raise ValueError("交付供應商折抵必須指定供應商。")
        bill_ids = list(allocation_amounts)
        bills = list(session.scalars(
            select(SupplierBill).where(
                SupplierBill.id.in_(bill_ids)
            ).order_by(SupplierBill.id).with_for_update()
        ).all())
        if len(bills) != len(bill_ids):
            raise ValueError("部分供應商帳單不存在。")
        for bill in bills:
            if (
                bill.company_id != company_id or bill.site_id != site_id
                or bill.supplier_id != supplier_id or bill.currency_code != "TWD"
                or bill.status == "VOID"
                or (purchase_id is not None and bill.purchase_id != purchase_id)
            ):
                raise ValueError("舊金折抵帳單必須屬於相同公司、據點、供應商且為有效新台幣帳單。")
            cash_paid = Decimal(session.scalar(
                select(func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0))
                .where(SupplierPaymentAllocation.bill_id == bill.id)
            ) or 0)
            gold_paid = Decimal(session.scalar(
                select(func.coalesce(func.sum(GoldMaterialSettlementAllocation.amount), 0))
                .where(GoldMaterialSettlementAllocation.bill_id == bill.id)
            ) or 0)
            requested = allocation_amounts[bill.id]
            if cash_paid + gold_paid + requested > bill.total_amount:
                raise ValueError(f"帳單 {bill.bill_no} 折抵後會超過應付總額。")
            paid_by_bill[bill.id] = cash_paid + gold_paid + requested

    if movement_type in OUTGOING_TYPES:
        available = _balance(session, company_id=company_id, site_id=site_id)
        if fine_gold_weight_g > available:
            raise ValueError(f"金料庫存不足；目前足金換算餘額 {available} 公克，本次需要 {fine_gold_weight_g} 公克。")

    movement = GoldMaterialMovement(
        company_id=company_id, site_id=site_id, supplier_id=supplier_id,
        purchase_id=purchase_id, movement_no=normalized_movement_no, movement_type=movement_type,
        source_type=normalized_source_type, purity_label=normalized_purity_label, purity_ratio=purity_ratio,
        gross_weight=gross_weight, loss_weight=loss_weight, net_weight=net_weight,
        weight_unit_code=weight_unit_code, fine_gold_weight_g=fine_gold_weight_g,
        gold_price_value=gold_price_value, gold_price_unit_code=gold_price_unit_code,
        deduction_amount=deduction_amount, valuation_amount=valuation_amount, note=note,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(movement)
    session.flush()

    if movement_type == "SUPPLIER_DELIVERY":
        for bill_id, amount in allocation_amounts.items():
            session.add(GoldMaterialSettlementAllocation(
                movement_id=movement.id, bill_id=bill_id, amount=amount
            ))
        for bill in bills:
            paid = paid_by_bill[bill.id]
            bill.status = "PAID" if paid == bill.total_amount else "PARTIALLY_PAID"

    session.flush()
    return (movement, True) if return_created else movement
