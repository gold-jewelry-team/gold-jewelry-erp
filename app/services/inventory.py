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


class StocktakeSnapshotConflict(ValueError):
    """Raised when stock changed after the stocktake baseline was captured."""


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
    reference_type: str = "STOCKTAKE",
) -> InventoryMovement | None:
    """Return a matching prior adjustment, or reject a key reused for other data."""
    if idempotency_key is None:
        return None
    existing = session.scalar(select(InventoryMovement).where(
        InventoryMovement.company_id == company_id,
        InventoryMovement.reference_type.in_({"STOCKTAKE", "MANUAL_TRANSFER", "MANUAL_ADJUSTMENT"}),
        InventoryMovement.reference_id == idempotency_key,
    ))
    if existing is None:
        return None

    expected_from = location_id if direction == "OUT" else None
    expected_to = location_id if direction == "IN" else None
    matches = (
        existing.reference_type == reference_type
        and existing.movement_type == "ADJUSTMENT"
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
            "此冪等識別碼已用於不同的庫存調整內容，請先核對原庫存異動紀錄後再操作。"
        )
    return existing


def get_idempotent_transfer(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    product_id: UUID,
    from_location_id: UUID,
    to_location_id: UUID,
    quantity: Decimal,
    weight: Decimal | None,
    weight_unit_code: str | None,
    note: str | None,
    idempotency_key: UUID | None,
) -> InventoryMovement | None:
    """Return the original manual transfer for an exact retry."""
    if idempotency_key is None:
        return None
    existing = session.scalar(select(InventoryMovement).where(
        InventoryMovement.company_id == company_id,
        InventoryMovement.reference_type.in_({"STOCKTAKE", "MANUAL_TRANSFER", "MANUAL_ADJUSTMENT"}),
        InventoryMovement.reference_id == idempotency_key,
    ))
    if existing is None:
        return None
    matches = (
        existing.reference_type == "MANUAL_TRANSFER"
        and existing.movement_type == "TRANSFER"
        and existing.site_id == site_id
        and existing.product_id == product_id
        and existing.from_location_id == from_location_id
        and existing.to_location_id == to_location_id
        and existing.quantity == quantity
        and existing.weight == weight
        and existing.weight_unit_code == weight_unit_code
        and existing.note == note
    )
    if not matches:
        raise InventoryIdempotencyConflict(
            "此調撥識別碼已用於不同庫存異動內容，請先核對原庫存流水。"
        )
    return existing


def apply_stocktake_adjustment_batch(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    items: list[dict],
) -> tuple[list[InventoryMovement], bool, int]:
    """Validate every stocktake snapshot before applying any adjustment.

    All product rows are locked in a stable order. Any stale quantity/weight
    snapshot aborts the whole transaction, so a newer sale/return/transfer
    cannot be overwritten by an old count.
    """
    if not items:
        raise ValueError("盤點清單不可為空。")
    if len(items) > 500:
        raise ValueError("單次盤點最多可處理 500 件商品。")

    product_ids = [item["product_id"] for item in items]
    idempotency_keys = [item["idempotency_key"] for item in items]
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("同一盤點批次不可重複包含同一商品。")
    if len(set(idempotency_keys)) != len(idempotency_keys):
        raise ValueError("盤點項目的冪等識別碼不可重複。")

    # Serialize batches for this company and lock inventory rows in stable order.
    company = session.scalar(
        select(Company).where(Company.id == company_id).with_for_update()
    )
    site = session.scalar(
        select(Site).where(
            Site.id == site_id,
            Site.company_id == company_id,
        ).with_for_update()
    )
    if company is None:
        raise ValueError("找不到指定公司。")
    if site is None:
        raise ValueError("據點不存在或不屬於指定公司。")

    location_ids = {item["location_id"] for item in items}
    locations = session.scalars(
        select(StorageLocation).where(
            StorageLocation.id.in_(location_ids),
            StorageLocation.site_id == site_id,
            StorageLocation.is_active.is_(True),
        ).with_for_update()
    ).all()
    if len(locations) != len(location_ids):
        raise ValueError("盤點儲存位置不存在、未啟用或不屬於指定據點。")

    products = session.scalars(
        select(Product)
        .where(
            Product.id.in_(product_ids),
            Product.company_id == company_id,
        )
        .order_by(Product.id)
        .with_for_update()
    ).all()
    products_by_id = {product.id: product for product in products}
    if len(products_by_id) != len(product_ids):
        raise ValueError("盤點清單包含不存在或不屬於指定公司的商品。")

    existing_rows = session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.reference_type == "STOCKTAKE",
            InventoryMovement.reference_id.in_(idempotency_keys),
        )
    ).all()
    existing_by_key = {row.reference_id: row for row in existing_rows}

    changed_items = []
    expected_keys = set()
    no_change_count = 0
    for item in items:
        product_id = item["product_id"]
        product = products_by_id[product_id]
        location_id = item["location_id"]
        expected_quantity = item["expected_quantity"]
        actual_quantity = item["actual_quantity"]
        expected_net_weight = item["expected_net_weight"]
        key = item["idempotency_key"]
        note = (item.get("note") or "").strip() or (
            f"條碼盤點差異（帳面：{expected_quantity}；實盤：{actual_quantity}）"
        )

        if expected_quantity < 0 or actual_quantity < 0:
            raise ValueError("盤點數量不可小於零。")
        if expected_net_weight < 0:
            raise ValueError("盤點基準重量不可小於零。")
        if actual_quantity != expected_quantity:
            expected_keys.add(key)
            direction = "IN" if actual_quantity > expected_quantity else "OUT"
            quantity = abs(actual_quantity - expected_quantity)
            expected_from = location_id if direction == "OUT" else None
            expected_to = location_id if direction == "IN" else None
            existing = existing_by_key.get(key)
            if existing is not None:
                matches = (
                    existing.movement_type == "ADJUSTMENT"
                    and existing.site_id == site_id
                    and existing.product_id == product_id
                    and existing.from_location_id == expected_from
                    and existing.to_location_id == expected_to
                    and existing.quantity == quantity
                    and existing.weight == expected_net_weight
                    and existing.weight_unit_code == product.weight_unit_code
                    and existing.note == note
                )
                if not matches:
                    raise InventoryIdempotencyConflict(
                        "盤點識別碼已用於不同商品或不同數量，請重新讀取盤點草稿。"
                    )
            changed_items.append({
                "item": item,
                "product": product,
                "direction": direction,
                "quantity": quantity,
                "note": note,
            })
        else:
            no_change_count += 1
            if key in existing_by_key:
                raise InventoryIdempotencyConflict(
                    "盤點識別碼先前已用於有差異的調整，不能改成無差異項目。"
                )

    # A previously committed batch is replayed only when every non-zero line
    # already has its exact movement. Partial prior commits are never continued.
    if existing_by_key:
        if set(existing_by_key) != expected_keys:
            raise InventoryIdempotencyConflict(
                "盤點調整紀錄與本次清單不一致；為避免部分重複入帳，請先查詢庫存異動紀錄。"
            )
        return [existing_by_key[key] for key in idempotency_keys if key in existing_by_key], True, no_change_count

    # Check all snapshots before writing the first movement.
    conflicts = []
    for item in items:
        product = products_by_id[item["product_id"]]
        current_quantity = get_stock_balance(
            session,
            product_id=product.id,
            location_id=item["location_id"],
        )
        expected_quantity = item["expected_quantity"]
        expected_weight = item["expected_net_weight"]
        if current_quantity != expected_quantity:
            conflicts.append(
                f"{product.product_code}（帳面數量已由 {expected_quantity} 變更為 {current_quantity}）"
            )
        if product.net_weight != expected_weight:
            conflicts.append(
                f"{product.product_code}（商品淨重已由 {expected_weight} 變更為 {product.net_weight}）"
            )
        if not product.is_active:
            conflicts.append(f"{product.product_code}（商品已停用）")
    if conflicts:
        raise StocktakeSnapshotConflict(
            "盤點期間商品資料已被其他交易變更，整批未入帳：" + "；".join(conflicts[:10])
        )

    movements = []
    for entry in changed_items:
        item = entry["item"]
        movement = create_inventory_movement(
            session,
            company_id=company_id,
            site_id=site_id,
            product_id=item["product_id"],
            movement_type="ADJUSTMENT",
            quantity=entry["quantity"],
            from_location_id=item["location_id"] if entry["direction"] == "OUT" else None,
            to_location_id=item["location_id"] if entry["direction"] == "IN" else None,
            weight=entry["product"].net_weight,
            weight_unit_code=entry["product"].weight_unit_code,
            note=entry["note"],
            idempotency_key=item["idempotency_key"],
        )
        movements.append(movement)

    return movements, False, no_change_count

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
    idempotency_reference_type: str = "STOCKTAKE",
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
        # Serialize keyed inventory writes before the idempotency lookup.
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

    if idempotency_key is not None:
        if movement_type == "ADJUSTMENT":
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
                reference_type=idempotency_reference_type,
            )
        elif movement_type == "TRANSFER":
            existing = get_idempotent_transfer(
                session,
                company_id=company_id,
                site_id=site_id,
                product_id=product_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                quantity=quantity,
                weight=weight,
                weight_unit_code=weight_unit_code,
                note=note,
                idempotency_key=idempotency_key,
            )
        else:
            raise InventoryIdempotencyConflict(
                "冪等識別碼目前僅支援庫存盤點調整及櫃位調撥。"
            )
        if existing is not None:
            return existing

    # Existing keyed movements are returned before checking current location
    # activation state; a retry must be able to retrieve the original ledger row.
    for location_id in (from_location_id, to_location_id):
        if location_id is not None:
            location = session.get(StorageLocation, location_id)
            if location is None or location.site_id != site_id or not location.is_active:
                raise ValueError("儲存位置不存在、未啟用或不屬於指定據點。")

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
        reference_type=(
            idempotency_reference_type if idempotency_key is not None and movement_type == "ADJUSTMENT"
            else "MANUAL_TRANSFER" if idempotency_key is not None and movement_type == "TRANSFER"
            else reference_type
        ),
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
