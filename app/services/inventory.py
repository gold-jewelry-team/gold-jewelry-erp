"""Validated inventory ledger operations and derived stock balances."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation


_INBOUND_ONLY = {"RECEIPT", "RETURN", "REPAIR_RETURN"}
_OUTBOUND_ONLY = {"SALE", "REPAIR_SEND"}
_ALLOWED_TYPES = _INBOUND_ONLY | _OUTBOUND_ONLY | {"TRANSFER", "ADJUSTMENT"}


def create_inventory_movement(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    product_id: UUID,
    movement_type: str,
    quantity: Decimal,
    from_location_id: UUID | None = None,
    to_location_id: UUID | None = None,
    weight: Decimal | None = None,
    weight_unit_code: str | None = None,
    occurred_at: datetime | None = None,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    note: str | None = None,
) -> InventoryMovement:
    """Validate ownership and movement direction before appending a ledger row."""
    if movement_type not in _ALLOWED_TYPES:
        raise ValueError("不支援的庫存異動類型。")
    if not isinstance(quantity, Decimal) or quantity <= 0:
        raise ValueError("異動數量必須是正數 Decimal。")
    if weight is not None and (not isinstance(weight, Decimal) or weight < 0):
        raise ValueError("重量必須是非負 Decimal。")

    company = session.get(Company, company_id)
    site = session.get(Site, site_id)
    product = session.get(Product, product_id)
    if company is None:
        raise ValueError("找不到指定公司。")
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    if product is None or product.company_id != company_id:
        raise ValueError("商品不存在或不屬於指定公司。")

    if movement_type in _INBOUND_ONLY and (from_location_id is not None or to_location_id is None):
        raise ValueError("此類異動必須指定目的儲存位置，且不可指定來源位置。")
    if movement_type in _OUTBOUND_ONLY and (from_location_id is None or to_location_id is not None):
        raise ValueError("此類異動必須指定來源儲存位置，且不可指定目的位置。")
    if movement_type == "TRANSFER" and (
        from_location_id is None or to_location_id is None or from_location_id == to_location_id
    ):
        raise ValueError("調撥必須指定兩個不同的儲存位置。")
    if movement_type == "ADJUSTMENT" and (from_location_id is None) == (to_location_id is None):
        raise ValueError("盤點調整必須且只能指定來源或目的儲存位置其中之一。")

    for location_id in (from_location_id, to_location_id):
        if location_id is not None:
            location = session.get(StorageLocation, location_id)
            if location is None or location.site_id != site_id:
                raise ValueError("儲存位置不存在或不屬於指定據點。")

    movement = InventoryMovement(
        company_id=company_id,
        site_id=site_id,
        product_id=product_id,
        movement_type=movement_type,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        weight=weight,
        weight_unit_code=weight_unit_code,
        occurred_at=occurred_at,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
    )
    session.add(movement)
    session.flush()
    return movement


def get_stock_balance(
    session: Session,
    *,
    product_id: UUID,
    location_id: UUID,
    as_of: datetime | None = None,
) -> Decimal:
    """Calculate a location's on-hand quantity from immutable movements."""
    statement = select(InventoryMovement).where(
        InventoryMovement.product_id == product_id,
        or_(
            InventoryMovement.from_location_id == location_id,
            InventoryMovement.to_location_id == location_id,
        ),
    )
    if as_of is not None:
        statement = statement.where(InventoryMovement.occurred_at <= as_of)

    balance = Decimal("0")
    for movement in session.scalars(statement):
        if movement.to_location_id == location_id:
            balance += movement.quantity
        if movement.from_location_id == location_id:
            balance -= movement.quantity
    return balance
