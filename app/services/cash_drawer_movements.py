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
    "BANK_DEPOSIT": "OUT", "BANK_WITHDRAWAL": "IN",
    "FLOAT_INCREASE": "IN", "FLOAT_DECREASE": "OUT",
    "OTHER_IN": "IN", "OTHER_OUT": "OUT",
}

def create_cash_drawer_movement(session: Session, *, company_id: UUID, site_id: UUID,
                                movement_type: str, amount: Decimal, description: str,
                                created_by_name: str, reference_no: str | None = None,
                                note: str | None = None) -> CashDrawerMovement:
    if movement_type not in MOVEMENT_DIRECTIONS:
        raise ValueError("不支援的現金櫃異動類型。")
    if not isinstance(amount, Decimal) or amount <= 0 or amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("異動金額必須是大於零且最多兩位小數的 Decimal。")
    description, actor = description.strip(), created_by_name.strip()
    if not description or not actor:
        raise ValueError("異動說明及經手人不可空白。")
    site = session.execute(select(Site).where(Site.id == site_id).with_for_update()).scalar_one_or_none()
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    created_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=site_id, at=created_at)
    row = CashDrawerMovement(company_id=company_id, site_id=site_id,
        movement_type=movement_type, direction=MOVEMENT_DIRECTIONS[movement_type],
        amount=amount, currency_code="TWD", description=description,
        created_by_name=actor, reference_no=reference_no, created_at=created_at, note=note)
    session.add(row)
    session.flush()
    return row
