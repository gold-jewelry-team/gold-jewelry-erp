"""Bank account and ledger APIs."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.bank_account import BankAccount, BankTransaction
from app.services.bank_accounts import create_bank_account, get_bank_account_balance, record_cash_deposit, record_cash_withdrawal, transfer_between_bank_accounts

router=APIRouter(prefix="/companies/{company_id}/bank-accounts",tags=["bank accounts"])
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

class BankAccountCreate(BaseModel):
    bank_name:str=Field(min_length=1,max_length=100)
    account_name:str=Field(min_length=1,max_length=120)
    account_last4:str=Field(pattern="^[0-9]{4}$")
    opening_balance:Decimal=Field(ge=0,max_digits=18,decimal_places=2)
    opening_balance_at:datetime

class BankAccountRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    company_id:UUID
    bank_name:str
    account_name:str
    account_last4:str
    currency_code:str
    opening_balance:Decimal
    opening_balance_at:datetime
    is_active:bool
    created_at:datetime

class BankAccountBalanceRead(BaseModel):
    account:BankAccountRead
    current_balance:Decimal

class BankTransactionRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    company_id:UUID
    bank_account_id:UUID
    site_id:UUID|None
    transfer_group_id:UUID|None
    transaction_type:str
    direction:str
    amount:Decimal
    currency_code:str
    reference_no:str|None
    description:str
    created_by_name:str
    occurred_at:datetime
    created_at:datetime
    note:str|None

class CashBankOperation(BaseModel):
    site_id:UUID
    amount:Decimal=Field(gt=0,max_digits=18,decimal_places=2)
    created_by_name:str=Field(min_length=1,max_length=120)
    reference_no:str|None=Field(default=None,max_length=100)
    note:str|None=Field(default=None,max_length=500)

class BankTransferCreate(BaseModel):
    from_account_id:UUID
    to_account_id:UUID
    amount:Decimal=Field(gt=0,max_digits=18,decimal_places=2)
    created_by_name:str=Field(min_length=1,max_length=120)
    reference_no:str|None=Field(default=None,max_length=100)
    note:str|None=Field(default=None,max_length=500)

def _commit(db,row):
    db.commit()
    if isinstance(row,tuple):
        for item in row: db.refresh(item)
    else: db.refresh(row)
    return row

@router.post("",response_model=BankAccountRead,status_code=201)
def post_bank_account(company_id:UUID,payload:BankAccountCreate,db:Session=Depends(get_db)):
    try:
        row=create_bank_account(db,company_id=company_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("",response_model=list[BankAccountBalanceRead])
def get_bank_accounts(company_id:UUID,include_inactive:bool=False,db:Session=Depends(get_db)):
    q=select(BankAccount).where(BankAccount.company_id==company_id)
    if not include_inactive: q=q.where(BankAccount.is_active.is_(True))
    accounts=list(db.scalars(q.order_by(BankAccount.bank_name,BankAccount.account_name)).all())
    return [{"account":a,"current_balance":get_bank_account_balance(db,a)} for a in accounts]

@router.get("/{account_id}/transactions",response_model=list[BankTransactionRead])
def get_bank_transactions(company_id:UUID,account_id:UUID,from_at:datetime|None=None,to_at:datetime|None=None,
                          limit:int=Query(default=100,ge=1,le=500),db:Session=Depends(get_db)):
    account=db.execute(select(BankAccount).where(BankAccount.id==account_id,BankAccount.company_id==company_id)).scalar_one_or_none()
    if account is None: raise HTTPException(status_code=404,detail="銀行帳戶不存在。")
    if from_at and to_at and from_at>to_at: raise HTTPException(status_code=422,detail="起始時間不可晚於結束時間。")
    q=select(BankTransaction).where(BankTransaction.company_id==company_id,BankTransaction.bank_account_id==account_id).order_by(BankTransaction.occurred_at.desc()).limit(limit)
    if from_at:q=q.where(BankTransaction.occurred_at>=from_at)
    if to_at:q=q.where(BankTransaction.occurred_at<=to_at)
    return list(db.scalars(q).all())

@router.post("/{account_id}/cash-deposits",response_model=BankTransactionRead,status_code=201)
def post_cash_deposit(company_id:UUID,account_id:UUID,payload:CashBankOperation,db:Session=Depends(get_db)):
    try:
        row=record_cash_deposit(db,company_id=company_id,bank_account_id=account_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post("/{account_id}/cash-withdrawals",response_model=BankTransactionRead,status_code=201)
def post_cash_withdrawal(company_id:UUID,account_id:UUID,payload:CashBankOperation,db:Session=Depends(get_db)):
    try:
        row=record_cash_withdrawal(db,company_id=company_id,bank_account_id=account_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post("/transfers",response_model=list[BankTransactionRead],status_code=201)
def post_bank_transfer(company_id:UUID,payload:BankTransferCreate,db:Session=Depends(get_db)):
    try:
        rows=transfer_between_bank_accounts(db,company_id=company_id,**payload.model_dump())
        db.commit()
        for row in rows: db.refresh(row)
        return list(rows)
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
