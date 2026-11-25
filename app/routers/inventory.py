from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.inventory_operation_request import InventoryOperationRequest
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers.schemas.inventory import (
    InventoryAdjustmentCreate, InventoryMovementRead, InventoryOperationRequestRead, InventoryTransferCreate, StockBalanceRead,
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
from app.services.inventory_operation_requests import fingerprint_inventory_operation
from app.services.inventory_operation_registry import (
    InventoryOperationRequestConflict,
    prepare_inventory_operation_request,
    mark_inventory_operation_failed,
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


@router.get("/operation-requests", response_model=list[InventoryOperationRequestRead])
def list_inventory_operation_requests(
    company_id: UUID,
    site_id: UUID | None = None,
    status: str | None = Query(default=None, pattern="^(PENDING|COMPLETED|FAILED)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List durable operation records so ambiguous writes can be inspected safely."""
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(InventoryOperationRequest).where(
        InventoryOperationRequest.company_id == company_id
    )
    if site_id is not None:
        statement = statement.where(InventoryOperationRequest.site_id == site_id)
    if status is not None:
        statement = statement.where(InventoryOperationRequest.status == status)
    return list(db.scalars(statement.order_by(
        InventoryOperationRequest.created_at.desc(),
        InventoryOperationRequest.id.desc(),
    ).offset(offset).limit(limit)).all())


@router.post(
    "/operation-requests/{request_id}/retry",
    response_model=InventoryMovementRead,
)
def retry_inventory_operation_request(
    company_id: UUID,
    request_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
):
    """Explicitly resume a stored operation; clients cannot replace its payload."""
    row = db.scalar(select(InventoryOperationRequest).where(
        InventoryOperationRequest.id == request_id,
        InventoryOperationRequest.company_id == company_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="找不到指定的庫存操作紀錄。")

    if row.status == "COMPLETED":
        movement = db.get(InventoryMovement, row.movement_id)
        if movement is None:
            raise HTTPException(status_code=409, detail="已完成操作缺少庫存流水，請人工檢查。")
        response.status_code = 200
        return movement
    if row.status not in {"PENDING", "FAILED"}:
        raise HTTPException(status_code=409, detail="此操作目前不可恢復。")

    try:
        stored_payload = row.payload.get("payload")
        if not isinstance(stored_payload, dict):
            raise InventoryOperationRequestConflict("保存的操作內容格式不正確，請人工檢查。")

        if row.operation_type == "MANUAL_ADJUSTMENT":
            payload = InventoryAdjustmentCreate.model_validate(stored_payload)
            legacy_lookup = lambda: get_idempotent_adjustment(
                db, company_id=company_id, site_id=payload.site_id,
                product_id=payload.product_id, location_id=payload.location_id,
                direction=payload.direction, quantity=payload.quantity,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                note=payload.note, idempotency_key=payload.idempotency_key,
                occurred_at=payload.occurred_at, reference_type="MANUAL_ADJUSTMENT",
            )
        elif row.operation_type == "MANUAL_TRANSFER":
            payload = InventoryTransferCreate.model_validate(stored_payload)
            legacy_lookup = lambda: get_idempotent_transfer(
                db, company_id=company_id, site_id=payload.site_id,
                product_id=payload.product_id, from_location_id=payload.from_location_id,
                to_location_id=payload.to_location_id, quantity=payload.quantity,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                note=payload.note, idempotency_key=payload.idempotency_key,
                occurred_at=payload.occurred_at,
            )
        else:
            raise InventoryOperationRequestConflict("不支援恢復此類庫存操作。")

        canonical, fingerprint = fingerprint_inventory_operation(
            operation_type=row.operation_type,
            company_id=company_id,
            site_id=row.site_id,
            payload=payload.model_dump(mode="python"),
        )
        if (
            payload.site_id != row.site_id
            or payload.idempotency_key != row.idempotency_key
            or canonical != row.payload
            or fingerprint != row.payload_fingerprint
        ):
            raise InventoryOperationRequestConflict("保存的操作內容驗證失敗，請人工檢查。")

        existing = legacy_lookup()
        if existing is not None:
            row.status = "COMPLETED"
            row.movement_id = existing.id
            row.failure_code = None
            row.failure_message = None
            row.completed_at = datetime.now(timezone.utc)
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
            response.status_code = 200
            return existing

        # This is an explicit admin action. Reuse only the immutable stored payload.
        row.status = "PENDING"
        row.failure_code = None
        row.failure_message = None
        if row.operation_type == "MANUAL_ADJUSTMENT":
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
        else:
            movement = create_inventory_movement(
                db, company_id=company_id, site_id=payload.site_id, product_id=payload.product_id,
                movement_type="TRANSFER", quantity=payload.quantity,
                from_location_id=payload.from_location_id, to_location_id=payload.to_location_id,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                occurred_at=payload.occurred_at, note=payload.note,
                idempotency_key=payload.idempotency_key,
            )

        row.status = "COMPLETED"
        row.movement_id = movement.id
        row.failure_code = None
        row.failure_message = None
        row.completed_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(movement)
        response.status_code = 200
        return movement
    except InventoryOperationRequestConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InventoryIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        # The original row lock was released by rollback. Use a conditional
        # update so a concurrent retry that completed in the meantime stays
        # COMPLETED instead of being overwritten by this late failure.
        db.execute(
            update(InventoryOperationRequest)
            .where(
                InventoryOperationRequest.id == request_id,
                InventoryOperationRequest.status.in_({"PENDING", "FAILED"}),
                InventoryOperationRequest.movement_id.is_(None),
            )
            .values(
                status="FAILED",
                failure_code="RETRY_VALIDATION_FAILED",
                failure_message=str(exc)[:300],
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="恢復操作結果尚待核對；請重新查看操作恢復清單。",
        ) from exc


@router.post("/adjustments", response_model=InventoryMovementRead, status_code=201)
def post_inventory_adjustment(company_id: UUID, payload: InventoryAdjustmentCreate,
                              response: Response, db: Session = Depends(get_db)):
    try:
        request_row, existing, _ = prepare_inventory_operation_request(
            db, company_id=company_id, site_id=payload.site_id,
            operation_type="MANUAL_ADJUSTMENT", idempotency_key=payload.idempotency_key,
            payload=payload.model_dump(mode="python"),
            legacy_movement_lookup=lambda: get_idempotent_adjustment(
                db, company_id=company_id, site_id=payload.site_id,
                product_id=payload.product_id, location_id=payload.location_id,
                direction=payload.direction, quantity=payload.quantity,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                note=payload.note, idempotency_key=payload.idempotency_key,
                occurred_at=payload.occurred_at, reference_type="MANUAL_ADJUSTMENT",
            ),
        )
        if existing is not None:
            response.status_code = 200
            return existing

        try:
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
            request_row.status = "COMPLETED"
            request_row.movement_id = movement.id
            request_row.completed_at = datetime.now(timezone.utc)
            request_row.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(movement)
            return movement
        except ValueError as exc:
            mark_inventory_operation_failed(
                db, request_id=request_row.id,
                failure_code="VALIDATION_FAILED", failure_message=str(exc),
            )
            status = 409 if isinstance(exc, InventoryIdempotencyConflict) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="庫存調整結果尚待核對；請先確認原始操作，不要重新建立請求。",
            ) from exc
    except InventoryOperationRequestConflict as exc:
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
        raise HTTPException(status_code=409, detail="庫存操作登記發生資料關聯衝突。") from exc


@router.post("/transfers", response_model=InventoryMovementRead, status_code=201)
def post_inventory_transfer(company_id: UUID, payload: InventoryTransferCreate,
                            response: Response, db: Session = Depends(get_db)):
    try:
        request_row, existing, _ = prepare_inventory_operation_request(
            db, company_id=company_id, site_id=payload.site_id,
            operation_type="MANUAL_TRANSFER", idempotency_key=payload.idempotency_key,
            payload=payload.model_dump(mode="python"),
            legacy_movement_lookup=lambda: get_idempotent_transfer(
                db, company_id=company_id, site_id=payload.site_id,
                product_id=payload.product_id, from_location_id=payload.from_location_id,
                to_location_id=payload.to_location_id, quantity=payload.quantity,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                note=payload.note, idempotency_key=payload.idempotency_key,
                occurred_at=payload.occurred_at,
            ),
        )
        if existing is not None:
            response.status_code = 200
            return existing

        try:
            movement = create_inventory_movement(
                db, company_id=company_id, site_id=payload.site_id, product_id=payload.product_id,
                movement_type="TRANSFER", quantity=payload.quantity,
                from_location_id=payload.from_location_id, to_location_id=payload.to_location_id,
                weight=payload.weight, weight_unit_code=payload.weight_unit_code,
                occurred_at=payload.occurred_at, note=payload.note,
                idempotency_key=payload.idempotency_key,
            )
            request_row.status = "COMPLETED"
            request_row.movement_id = movement.id
            request_row.completed_at = datetime.now(timezone.utc)
            request_row.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(movement)
            return movement
        except ValueError as exc:
            mark_inventory_operation_failed(
                db, request_id=request_row.id,
                failure_code="VALIDATION_FAILED", failure_message=str(exc),
            )
            status = 409 if isinstance(exc, InventoryIdempotencyConflict) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="櫃位調撥結果尚待核對；請先確認原始操作，不要重新建立請求。",
            ) from exc
    except InventoryOperationRequestConflict as exc:
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
        raise HTTPException(status_code=409, detail="庫存操作登記發生資料關聯衝突。") from exc
