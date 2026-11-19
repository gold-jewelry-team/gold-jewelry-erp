"""Daily cash count APIs."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.cash_count import DailyCashCount
from app.services.cash_counts import create_cash_count, review_cash_count

router = APIRouter(prefix="/companies/{company_id}/sites/{site_id}/daily-closings/{closing_id}/cash-count", tags=["daily cash count"])
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

class CashCountCreate(BaseModel):
    opening_cash_float: Decimal = Field(ge=0,max_digits=18,decimal_places=2)
    counted_cash_amount: Decimal = Field(ge=0,max_digits=18,decimal_places=2)
    counted_by_name: str = Field(min_length=1,max_length=120)
    count_note: str | None = Field(default=None,max_length=500)

class CashCountReview(BaseModel):
    reviewed_by_name: str = Field(min_length=1,max_length=120)
    review_note: str | None = Field(default=None,max_length=500)

class CashCountRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    closing_id: UUID
    currency_code: str
    opening_cash_float: Decimal
    expected_cash_amount: Decimal
    counted_cash_amount: Decimal
    cash_variance: Decimal
    counted_by_name: str
    counted_at: datetime
    count_note: str | None
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    review_note: str | None

@router.post("",response_model=CashCountRead,status_code=201)
def post_cash_count(company_id: UUID,site_id: UUID,closing_id: UUID,payload: CashCountCreate,db: Session=Depends(get_db)):
    try:
        row=create_cash_count(db,company_id=company_id,site_id=site_id,closing_id=closing_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("",response_model=CashCountRead)
def get_cash_count(company_id: UUID,site_id: UUID,closing_id: UUID,db: Session=Depends(get_db)):
    row=db.scalar(select(DailyCashCount).where(DailyCashCount.company_id==company_id,DailyCashCount.site_id==site_id,DailyCashCount.closing_id==closing_id))
    if row is None: raise HTTPException(status_code=404,detail="找不到現金盤點紀錄。")
    return row

@router.post("/{cash_count_id}/review",response_model=CashCountRead)
def post_cash_count_review(company_id: UUID,site_id: UUID,closing_id: UUID,cash_count_id: UUID,payload: CashCountReview,db: Session=Depends(get_db)):
    try:
        row=review_cash_count(db,company_id=company_id,site_id=site_id,cash_count_id=cash_count_id,**payload.model_dump())
        if row.closing_id != closing_id: raise ValueError("現金盤點紀錄不屬於指定每日結帳。")
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
