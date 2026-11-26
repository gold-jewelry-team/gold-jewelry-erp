"""Physical cash drawer movement workflows."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.site import Site
from app.services.daily_closing import assert_business_day_open

MOVEMENT_DIRECTIONS = {
    "FLOAT_INCREASE": "IN",
    "FLOAT_DECREASE": "OUT",
    "OTHER_IN": "IN",
    "OTHER_OUT": "OUT",
}


class CashDrawerMovementIdempotencyConflict(ValueError):
    """Raised when a cash drawer request key is reused for different details."""


def create_cash_drawer_movement(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    movement_type: str,
    amount: Decimal,
    description: str,
    created_by_name: str,
    reference_no: str | None = None,
    note: str | None = None,
    idempotency_key: UUID | None = None,
    return_created: bool = False,
) -> CashDrawerMovement | tuple[CashDrawerMovement, bool]:
    if movement_type in {"BANK_DEPOSIT", "BANK_WITHDRAWAL"}:
        raise ValueError(
            "銀行存提款請至「銀行帳戶／對帳」頁面執行，系統會同步建立銀行流水與現金櫃異動。"
        )
    if movement_type not in MOVEMENT_DIRECTIONS:
        raise ValueError("不支援的現金櫃異動類型。")
    if not isinstance(amount, Decimal) or amount <= 0 or amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("異動金額必須是大於零且最多兩位小數的 Decimal。")
    description, actor = description.strip(), created_by_name.strip()
    if not description or not actor:
        raise ValueError("異動說明及經手人不可空白。")

    # Lock the site before checking the idempotency key so concurrent retries
    # at the same cash drawer serialize before the append-only ledger write.
    site = session.execute(
        select(Site).where(Site.id == site_id).with_for_update()
    ).scalar_one_or_none()
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")

    direction = MOVEMENT_DIRECTIONS[movement_type]
    if idempotency_key is not None:
        existing = session.scalar(select(CashDrawerMovement).where(
            CashDrawerMovement.site_id == site_id,
            CashDrawerMovement.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            matches = (
                existing.company_id == company_id
                and existing.site_id == site_id
                and existing.movement_type == movement_type
                and existing.direction == direction
                and existing.amount == amount
                and existing.currency_code == "TWD"
                and existing.description == description
                and existing.created_by_name == actor
                and existing.reference_no == reference_no
                and existing.note == note
            )
            if not matches:
                raise CashDrawerMovementIdempotencyConflict(
                    "此現金櫃異動識別碼已用於不同的異動內容，請查閱原紀錄後再操作。"
                )
            return (existing, False) if return_created else existing

    created_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=site_id, at=created_at)
    row = CashDrawerMovement(
        company_id=company_id,
        site_id=site_id,
        movement_type=movement_type,
        direction=direction,
        amount=amount,
        currency_code="TWD",
        description=description,
        created_by_name=actor,
        reference_no=reference_no,
        idempotency_key=idempotency_key,
        created_at=created_at,
        note=note,
    )
    session.add(row)
    session.flush()
    return (row, True) if return_created else row
