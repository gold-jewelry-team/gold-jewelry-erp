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


class InventoryIdempotencyConflict(ValueError):
    """Raised when a retry key is reused for a different inventory adjustment."""


def get_idempotent_adjustment(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    product_id: UUID,
    location_id: UUID,
    direction: str,
    quantity: Decimal,
    weight: Decimal | None,
    weight_unit_code: str | None,
    note: str | None,
    idempotency_key: UUID | None,
) -> InventoryMovement | None:
    """Return a matching prior adjustment, or reject a key reused for other data."""
    if idempotency_key is None:
        return None
    existing = session.scalar(select(InventoryMovement).where(
        InventoryMovement.company_id == company_id,
        InventoryMovement.reference_type == "STOCKTAKE",
        InventoryMovement.reference_id == idempotency_key,
    ))
    if existing is None:
        return None

    expected_from = location_id if direction == "OUT" else None
    expected_to = location_id if direction == "IN" else None
    matches = (
        existing.movement_type == "ADJUSTMENT"
        and existing.site_id == site_id
        and existing.product_id == product_id
        and existing.from_location_id == expected_from
        and existing.to_location_id == expected_to
        and existing.quantity == quantity
        and existing.weight == weight
        and existing.weight_unit_code == weight_unit_code
        and existing.note == note
    )
    if not matches:
        raise InventoryIdempotencyConflict(
            "此冪等識別碼已用於不同的庫存調整內容，請重新讀取盤點資料後再操作。"
        )
    return existing


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
    idempotency_key: UUID | None = None,
) -> InventoryMovement:
    """Validate ownership and movement direction before appending a ledger row."""
    if movement_type not in _ALLOWED_TYPES:
        raise ValueError("不支援的庫存異動類型。")
    if not isinstance(quantity, Decimal) or quantity <= 0:
        raise ValueError("異動數量必須是正數 Decimal。")
    if weight is not None and (not isinstance(weight, Decimal) or weight < 0):
        raise ValueError("重量必須是非負 Decimal。")

    company_query = select(Company).where(Company.id == company_id)
    if idempotency_key is not None:
        # Serialize keyed stocktake writes before the idempotency lookup.
        company_query = company_query.with_for_update()
    company = session.scalar(company_query)
    site = session.get(Site, site_id)
    product = session.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    ).scalar_one_or_none()
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
            if location is None or location.site_id != site_id or not location.is_active:
                raise ValueError("儲存位置不存在、未啟用或不屬於指定據點。")

    if idempotency_key is not None:
        if movement_type != "ADJUSTMENT":
            raise InventoryIdempotencyConflict("冪等識別碼目前僅支援庫存盤點調整。")
        existing = get_idempotent_adjustment(
            session,
            company_id=company_id,
            site_id=site_id,
            product_id=product_id,
            location_id=from_location_id or to_location_id,
            direction="OUT" if from_location_id is not None else "IN",
            quantity=quantity,
            weight=weight,
            weight_unit_code=weight_unit_code,
            note=note,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing

    # Serialize movements for one product in PostgreSQL and prevent negative stock.
    if from_location_id is not None:
        available = get_stock_balance(
            session, product_id=product_id, location_id=from_location_id
        )
        if available < quantity:
            raise ValueError(f"庫存不足，目前可用數量：{available}。")

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
        reference_type="STOCKTAKE" if idempotency_key is not None else reference_type,
        reference_id=idempotency_key if idempotency_key is not None else reference_id,
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
