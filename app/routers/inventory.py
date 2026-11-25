from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers.schemas.inventory import (
    InventoryAdjustmentCreate, InventoryMovementRead, InventoryTransferCreate, StockBalanceRead,
    StocktakeAdjustmentBatchCreate, StocktakeAdjustmentBatchRead,
)
from app.services.inventory import (
    InventoryIdempotencyConflict,
    create_inventory_movement,
    get_idempotent_adjustment,
    get_idempotent_transfer,
    StocktakeSnapshotConflict,
    apply_stocktake_adjustment_batch,
)

router = APIRouter(prefix="/companies/{company_id}/inventory", tags=["inventory"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/stock", response_model=list[StockBalanceRead])
def list_stock_balances(
    company_id: UUID,
    site_id: UUID | None = None,
    location_id: UUID | None = None,
    product_id: UUID | None = None,
    as_of: datetime | None = None,
    include_zero: bool = False,
    db: Session = Depends(get_db),
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(InventoryMovement).where(InventoryMovement.company_id == company_id)
    if site_id:
        statement = statement.where(InventoryMovement.site_id == site_id)
    if product_id:
        statement = statement.where(InventoryMovement.product_id == product_id)
    if location_id:
        statement = statement.where(or_(
            InventoryMovement.from_location_id == location_id,
            InventoryMovement.to_location_id == location_id,
        ))
    if as_of:
        statement = statement.where(InventoryMovement.occurred_at <= as_of)

    balances: dict[tuple[UUID, UUID], Decimal] = defaultdict(lambda: Decimal("0"))
    site_by_key: dict[tuple[UUID, UUID], UUID] = {}
    for movement in db.scalars(statement):
        if movement.to_location_id is not None and (location_id is None or movement.to_location_id == location_id):
            key = (movement.product_id, movement.to_location_id)
            balances[key] += movement.quantity
            site_by_key[key] = movement.site_id
        if movement.from_location_id is not None and (location_id is None or movement.from_location_id == location_id):
            key = (movement.product_id, movement.from_location_id)
            balances[key] -= movement.quantity
            site_by_key[key] = movement.site_id

    product_ids = {key[0] for key in balances}
    location_ids = {key[1] for key in balances}
    products = {p.id: p for p in db.scalars(select(Product).where(
        Product.company_id == company_id, Product.id.in_(product_ids)
    )).all()} if product_ids else {}
    locations = {loc.id: loc for loc in db.scalars(select(StorageLocation).where(
        StorageLocation.id.in_(location_ids)
    )).all()} if location_ids else {}
    sites = {s.id: s for s in db.scalars(select(Site).where(
        Site.company_id == company_id
    )).all()}
    result = []
    for (pid, lid), quantity in balances.items():
        if not include_zero and quantity == 0:
            continue
        product = products.get(pid)
        location = locations.get(lid)
        sid = site_by_key[(pid, lid)]
        site = sites.get(sid)
        if product is None or location is None or site is None:
            continue
        result.append(StockBalanceRead(
            company_id=company_id, site_id=sid, site_name=site.name,
            product_id=pid, product_code=product.product_code, barcode=product.barcode,
            product_name=product.name, location_id=lid, location_code=location.code,
            location_name=location.name, quantity=quantity,
        ))
    return sorted(result, key=lambda row: (row.product_code, row.site_name, row.location_code))


@router.get("/movements", response_model=list[InventoryMovementRead])
def list_inventory_movements(
    company_id: UUID,
    site_id: UUID | None = None,
    product_id: UUID | None = None,
    location_id: UUID | None = None,
    movement_type: str | None = Query(default=None, pattern="^(RECEIPT|SALE|TRANSFER|ADJUSTMENT|RETURN|REPAIR_SEND|REPAIR_RETURN)$"),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(InventoryMovement).where(InventoryMovement.company_id == company_id)
    if site_id:
        statement = statement.where(InventoryMovement.site_id == site_id)
    if product_id:
        statement = statement.where(InventoryMovement.product_id == product_id)
    if location_id:
        statement = statement.where(or_(
            InventoryMovement.from_location_id == location_id,
            InventoryMovement.to_location_id == location_id,
        ))
    if movement_type:
        statement = statement.where(InventoryMovement.movement_type == movement_type)
    if since:
        statement = statement.where(InventoryMovement.occurred_at >= since)
    if until:
        statement = statement.where(InventoryMovement.occurred_at <= until)
    rows = list(db.scalars(statement.order_by(
        InventoryMovement.occurred_at.desc(), InventoryMovement.created_at.desc()
    ).limit(limit)).all())
    return [
        InventoryMovementRead.model_validate(row).model_copy(update={
            "reference_type": (
                "PURCHASE_LINE" if (row.reference_type or "").startswith("PR-")
                else row.reference_type
            )
        })
        for row in rows
    ]


@router.post(
    "/stocktake-adjustments",
    response_model=StocktakeAdjustmentBatchRead,
    status_code=201,
)
def post_stocktake_adjustment_batch(
    company_id: UUID,
    payload: StocktakeAdjustmentBatchCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        movements, replayed, no_change_count = apply_stocktake_adjustment_batch(
            db,
            company_id=company_id,
            site_id=payload.site_id,
            items=[item.model_dump() for item in payload.items],
        )
        db.commit()
        for movement in movements:
            db.refresh(movement)
        if replayed:
            response.status_code = 200
        return StocktakeAdjustmentBatchRead(
            applied_count=len(payload.items),
            adjustment_count=len(movements),
            no_change_count=no_change_count,
            replayed=replayed,
            movements=movements,
        )
    except StocktakeSnapshotConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InventoryIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="盤點調整重複或資料關聯衝突；整批未入帳。") from exc


@router.post("/adjustments", response_model=InventoryMovementRead, status_code=201)
def post_inventory_adjustment(company_id: UUID, payload: InventoryAdjustmentCreate,
                              response: Response, db: Session = Depends(get_db)):
    try:
        existing = get_idempotent_adjustment(
            db,
            company_id=company_id,
            site_id=payload.site_id,
            product_id=payload.product_id,
            location_id=payload.location_id,
            direction=payload.direction,
            quantity=payload.quantity,
            weight=payload.weight,
            weight_unit_code=payload.weight_unit_code,
            note=payload.note,
            idempotency_key=payload.idempotency_key,
            reference_type="MANUAL_ADJUSTMENT",
        )
        if existing is not None:
            response.status_code = 200
            return existing
        movement = create_inventory_movement(
            db, company_id=company_id, site_id=payload.site_id, product_id=payload.product_id,
            movement_type="ADJUSTMENT", quantity=payload.quantity,
            from_location_id=payload.location_id if payload.direction == "OUT" else None,
            to_location_id=payload.location_id if payload.direction == "IN" else None,
            weight=payload.weight, weight_unit_code=payload.weight_unit_code,
            occurred_at=payload.occurred_at, note=payload.note,
            idempotency_key=payload.idempotency_key,
            idempotency_reference_type="MANUAL_ADJUSTMENT",
        )
        db.commit()
        db.refresh(movement)
        return movement
    except InventoryIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        if payload.idempotency_key is not None:
            try:
                existing = get_idempotent_adjustment(
                    db,
                    company_id=company_id,
                    site_id=payload.site_id,
                    product_id=payload.product_id,
                    location_id=payload.location_id,
                    direction=payload.direction,
                    quantity=payload.quantity,
                    weight=payload.weight,
                    weight_unit_code=payload.weight_unit_code,
                    note=payload.note,
                    idempotency_key=payload.idempotency_key,
                    reference_type="MANUAL_ADJUSTMENT",
                )
            except InventoryIdempotencyConflict as conflict:
                raise HTTPException(status_code=409, detail=str(conflict)) from conflict
            if existing is not None:
                response.status_code = 200
                return existing
        raise HTTPException(status_code=409, detail="庫存調整重複或資料關聯衝突。") from exc


@router.post("/transfers", response_model=InventoryMovementRead, status_code=201)
def post_inventory_transfer(company_id: UUID, payload: InventoryTransferCreate,
                            response: Response, db: Session = Depends(get_db)):
    try:
        existing = get_idempotent_transfer(
            db, company_id=company_id, site_id=payload.site_id,
            product_id=payload.product_id, from_location_id=payload.from_location_id,
            to_location_id=payload.to_location_id, quantity=payload.quantity,
            weight=payload.weight, weight_unit_code=payload.weight_unit_code,
            note=payload.note, idempotency_key=payload.idempotency_key,
        )
        if existing is not None:
            response.status_code = 200
            return existing
        movement = create_inventory_movement(
            db, company_id=company_id, site_id=payload.site_id, product_id=payload.product_id,
            movement_type="TRANSFER", quantity=payload.quantity,
            from_location_id=payload.from_location_id, to_location_id=payload.to_location_id,
            weight=payload.weight, weight_unit_code=payload.weight_unit_code,
            occurred_at=payload.occurred_at, note=payload.note,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        db.refresh(movement)
        return movement
    except InventoryIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        try:
            existing = get_idempotent_transfer(
                db, company_id=company_id, site_id=payload.site_id,
                product_id=payload.product_id, from_location_id=payload.from_location_id,
                to_location_id=payload.to_location_id, quantity=payload.quantity,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                note=payload.note, idempotency_key=payload.idempotency_key,
            )
        except InventoryIdempotencyConflict as conflict:
            raise HTTPException(status_code=409, detail=str(conflict)) from conflict
        if existing is not None:
            response.status_code = 200
            return existing
        raise HTTPException(status_code=409, detail="櫃位調撥重複或資料關聯衝突。") from exc
