"""Cash drawer movement APIs."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.cash_drawer_movement import CashDrawerMovement
from app.services.cash_drawer_movements import (
    CashDrawerMovementIdempotencyConflict,
    create_cash_drawer_movement,
)

router = APIRouter(prefix="/companies/{company_id}/sites/{site_id}/cash-drawer-movements", tags=["cash drawer"])
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

class CashDrawerMovementCreate(BaseModel):
    movement_type: str = Field(pattern="^(BANK_DEPOSIT|BANK_WITHDRAWAL|FLOAT_INCREASE|FLOAT_DECREASE|OTHER_IN|OTHER_OUT)$")
    amount: Decimal = Field(gt=0,max_digits=18,decimal_places=2)
    description: str = Field(min_length=1,max_length=200)
    created_by_name: str = Field(min_length=1,max_length=120)
    reference_no: str | None = Field(default=None,max_length=100)
    note: str | None = Field(default=None,max_length=500)
    idempotency_key: UUID | None = None

class CashDrawerMovementRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    movement_type: str
    direction: str
    amount: Decimal
    currency_code: str
    reference_no: str | None
    description: str
    created_by_name: str
    created_at: datetime
    note: str | None

@router.post("",response_model=CashDrawerMovementRead,status_code=201)
def post_cash_drawer_movement(company_id: UUID,site_id: UUID,payload: CashDrawerMovementCreate,response: Response,db: Session=Depends(get_db)):
    try:
        row,created=create_cash_drawer_movement(
            db,company_id=company_id,site_id=site_id,return_created=True,**payload.model_dump()
        )
        if not created:
            response.status_code=200
        db.commit(); db.refresh(row); return row
    except CashDrawerMovementIdempotencyConflict as exc:
        db.rollback(); raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409,detail="現金櫃異動識別碼重複或資料關聯衝突。") from exc

@router.get("",response_model=list[CashDrawerMovementRead])
def list_cash_drawer_movements(company_id: UUID,site_id: UUID,from_at: datetime | None=None,to_at: datetime | None=None,
                               limit: int=Query(default=100,ge=1,le=500),db: Session=Depends(get_db)):
    if from_at and to_at and from_at>to_at:
        raise HTTPException(status_code=422,detail="起始時間不可晚於結束時間。")
    q=select(CashDrawerMovement).where(CashDrawerMovement.company_id==company_id,CashDrawerMovement.site_id==site_id).order_by(CashDrawerMovement.created_at.desc()).limit(limit)
    if from_at: q=q.where(CashDrawerMovement.created_at>=from_at)
    if to_at: q=q.where(CashDrawerMovement.created_at<=to_at)
    return list(db.scalars(q).all())
