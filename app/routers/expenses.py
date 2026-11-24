"""Operating expense APIs."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.operating_expense import OperatingExpense
from app.services.daily_closing import assert_business_day_open
from app.services.operating_expenses import (
    ExpenseIdempotencyConflict,
    ExpensePaymentIdempotencyConflict,
    create_expense,
    pay_expense,
)

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

class ExpenseUpdate(BaseModel):
    expense_no: str | None = Field(default=None, min_length=1, max_length=50)
    expense_date: date | None = None
    category_code: str | None = Field(default=None, pattern="^(RENT|UTILITIES|SALARIES|SUPPLIES|SHIPPING|REPAIR|OTHER)$")
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    payee: str | None = Field(default=None, max_length=120)
    receipt_no: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


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
def post_expense(company_id: UUID,payload: ExpenseCreate,response: Response,db: Session=Depends(get_db)):
    try:
        row,created=create_expense(
            db,company_id=company_id,return_created=True,**payload.model_dump()
        )
        if not created:
            response.status_code=200
        db.commit(); db.refresh(row); return row
    except ExpenseIdempotencyConflict as exc:
        db.rollback(); raise HTTPException(status_code=409,detail=str(exc)) from exc
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

@router.patch("/{expense_id}", response_model=ExpenseRead)
def patch_expense(company_id: UUID, expense_id: UUID, payload: ExpenseUpdate, db: Session = Depends(get_db)):
    row = db.scalar(select(OperatingExpense).where(
        OperatingExpense.company_id == company_id,
        OperatingExpense.id == expense_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="找不到指定營業費用。")
    if row.status != "UNPAID":
        raise HTTPException(status_code=409, detail="只有未付款費用可以修改；已付款或已作廢紀錄不可直接更改。")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="請至少提供一個要修改的欄位。")
    if any(changes.get(field) is None for field in ("expense_no", "expense_date", "category_code", "description", "amount") if field in changes):
        raise HTTPException(status_code=422, detail="費用單號、日期、分類、說明與金額不可為空。")
    try:
        assert_business_day_open(db, site_id=row.site_id, at=datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for key, value in changes.items():
        setattr(row, key, value)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="費用單號重複或資料關聯衝突。") from exc


@router.post("/{expense_id}/void", response_model=ExpenseRead)
def void_expense(company_id: UUID, expense_id: UUID, db: Session = Depends(get_db)):
    row = db.scalar(select(OperatingExpense).where(
        OperatingExpense.company_id == company_id,
        OperatingExpense.id == expense_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="找不到指定營業費用。")
    if row.status != "UNPAID":
        raise HTTPException(status_code=409, detail="只有未付款費用可以作廢；已付款或已作廢紀錄不可直接更改。")
    try:
        assert_business_day_open(db, site_id=row.site_id, at=datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row.status = "VOID"
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="費用作廢失敗。") from exc


@router.post("/{expense_id}/pay",response_model=ExpenseRead)
def post_expense_payment(company_id: UUID,expense_id: UUID,payload: ExpensePay,response: Response,db: Session=Depends(get_db)):
    try:
        row,created=pay_expense(
            db,company_id=company_id,expense_id=expense_id,
            payment_method=payload.payment_method,return_created=True
        )
        if not created:
            response.status_code=200
        db.commit(); db.refresh(row); return row
    except ExpensePaymentIdempotencyConflict as exc:
        db.rollback(); raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
