"""Operating expense APIs."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.operating_expense import OperatingExpense
from app.services.operating_expenses import create_expense, pay_expense

router = APIRouter(prefix="/companies/{company_id}/operating-expenses", tags=["operating expenses"])
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

class ExpenseCreate(BaseModel):
    site_id: UUID
    expense_no: str = Field(min_length=1,max_length=50)
    expense_date: date
    category_code: str = Field(pattern="^(RENT|UTILITIES|SALARIES|SUPPLIES|SHIPPING|REPAIR|OTHER)$")
    description: str = Field(min_length=1,max_length=200)
    amount: Decimal = Field(gt=0,max_digits=18,decimal_places=2)
    payee: str | None = Field(default=None,max_length=120)
    payment_method: str | None = Field(default=None,pattern="^(CASH|CARD|TRANSFER|OTHER)$")
    receipt_no: str | None = Field(default=None,max_length=100)
    note: str | None = Field(default=None,max_length=500)

class ExpensePay(BaseModel):
    payment_method: str = Field(pattern="^(CASH|CARD|TRANSFER|OTHER)$")

class ExpenseRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    expense_no: str
    expense_date: date
    category_code: str
    description: str
    payee: str | None
    amount: Decimal
    currency_code: str
    status: str
    payment_method: str | None
    paid_at: datetime | None
    receipt_no: str | None
    note: str | None

@router.post("",response_model=ExpenseRead,status_code=201)
def post_expense(company_id: UUID,payload: ExpenseCreate,db: Session=Depends(get_db)):
    try:
        row=create_expense(db,company_id=company_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409,detail="費用單號重複或資料關聯衝突。") from exc

@router.get("",response_model=list[ExpenseRead])
def list_expenses(company_id: UUID,site_id: UUID | None=None,status: str | None=Query(default=None,pattern="^(UNPAID|PAID|VOID)$"),
                  category_code: str | None=None,from_date: date | None=None,to_date: date | None=None,
                  limit: int=Query(default=100,ge=1,le=500),db: Session=Depends(get_db)):
    q=select(OperatingExpense).where(OperatingExpense.company_id==company_id).order_by(OperatingExpense.expense_date.desc()).limit(limit)
    if site_id: q=q.where(OperatingExpense.site_id==site_id)
    if status: q=q.where(OperatingExpense.status==status)
    if category_code: q=q.where(OperatingExpense.category_code==category_code)
    if from_date: q=q.where(OperatingExpense.expense_date>=from_date)
    if to_date: q=q.where(OperatingExpense.expense_date<=to_date)
    if from_date and to_date and from_date>to_date: raise HTTPException(status_code=422,detail="起始日期不可晚於結束日期。")
    return list(db.scalars(q).all())

@router.post("/{expense_id}/pay",response_model=ExpenseRead)
def post_expense_payment(company_id: UUID,expense_id: UUID,payload: ExpensePay,db: Session=Depends(get_db)):
    try:
        row=pay_expense(db,company_id=company_id,expense_id=expense_id,payment_method=payload.payment_method)
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
