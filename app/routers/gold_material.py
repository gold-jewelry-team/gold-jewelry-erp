from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.gold_material import GoldMaterialMovement
from app.models.site import Site
from app.routers.schemas.gold_material import (
    GoldMaterialBalanceRead, GoldMaterialMovementCreate, GoldMaterialMovementRead,
)
from app.services.gold_material import INCOMING_TYPES, WEIGHT_GRAMS, record_gold_material_movement

router = APIRouter(prefix="/companies/{company_id}/gold-material", tags=["gold material"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/balance", response_model=GoldMaterialBalanceRead)
def get_gold_material_balance(company_id: UUID, site_id: UUID, db: Session = Depends(get_db)):
    site = db.scalar(select(Site).where(
        Site.id == site_id,
        Site.company_id == company_id,
    ))
    if site is None:
        raise HTTPException(status_code=404, detail="找不到指定公司據點。")
    signed_weight = case(
        (GoldMaterialMovement.movement_type.in_(INCOMING_TYPES), GoldMaterialMovement.fine_gold_weight_g),
        else_=-GoldMaterialMovement.fine_gold_weight_g,
    )
    balance = db.scalar(select(func.coalesce(func.sum(signed_weight), 0)).where(
        GoldMaterialMovement.company_id == company_id,
        GoldMaterialMovement.site_id == site_id,
    ))
    return GoldMaterialBalanceRead(
        company_id=company_id, site_id=site_id, fine_gold_weight_g=balance or 0
    )


@router.get("/movements", response_model=list[GoldMaterialMovementRead])
def list_gold_material_movements(
    company_id: UUID,
    site_id: UUID | None = None,
    movement_type: str | None = Query(default=None, pattern="^(OPENING|RECEIPT|ADJUSTMENT_IN|ADJUSTMENT_OUT|SUPPLIER_DELIVERY)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = select(GoldMaterialMovement).options(
        selectinload(GoldMaterialMovement.allocations)
    ).where(GoldMaterialMovement.company_id == company_id)
    if site_id:
        statement = statement.where(GoldMaterialMovement.site_id == site_id)
    if movement_type:
        statement = statement.where(GoldMaterialMovement.movement_type == movement_type)
    return list(db.scalars(statement.order_by(GoldMaterialMovement.occurred_at.desc()).limit(limit)).all())


@router.post("/movements", response_model=GoldMaterialMovementRead, status_code=201)
def post_gold_material_movement(
    company_id: UUID, payload: GoldMaterialMovementCreate, db: Session = Depends(get_db)
):
    try:
        movement = record_gold_material_movement(
            db, company_id=company_id, site_id=payload.site_id,
            supplier_id=payload.supplier_id, purchase_id=payload.purchase_id,
            movement_no=payload.movement_no, movement_type=payload.movement_type,
            source_type=payload.source_type, purity_label=payload.purity_label,
            purity_ratio=payload.purity_ratio, gross_weight=payload.gross_weight,
            loss_weight=payload.loss_weight, weight_unit_code=payload.weight_unit_code,
            gold_price_value=payload.gold_price_value,
            gold_price_unit_code=payload.gold_price_unit_code,
            deduction_amount=payload.deduction_amount,
            allocations=[item.model_dump() for item in payload.allocations],
            note=payload.note,
        )
        movement_id = movement.id
        db.commit()
        return db.scalar(select(GoldMaterialMovement).options(
            selectinload(GoldMaterialMovement.allocations)
        ).where(GoldMaterialMovement.id == movement_id))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="金料異動單號重複或資料關聯衝突。") from exc
