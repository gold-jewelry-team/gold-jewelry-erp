"""Bank reconciliation snapshot API."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.bank_reconciliation import BankReconciliationSnapshot
from app.services.bank_reconciliation_snapshots import create_reconciliation_snapshot

router=APIRouter(prefix="/companies/{company_id}/bank-accounts/{account_id}/reconciliation-snapshots",tags=["bank reconciliation"])
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

class SnapshotCreate(BaseModel):
    import_id:UUID
    period_start:date
    period_end:date
    statement_opening_balance:Decimal
    statement_closing_balance:Decimal
    reconciled_by_name:str=Field(min_length=1,max_length=120)
    note:str|None=Field(default=None,max_length=500)

class SnapshotRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    company_id:UUID
    bank_account_id:UUID
    import_id:UUID
    period_start:date
    period_end:date
    statement_opening_balance:Decimal
    statement_closing_balance:Decimal
    statement_net_movement:Decimal
    ledger_net_movement:Decimal
    net_difference:Decimal
    statement_line_count:int
    matched_line_count:int
    unmatched_line_count:int
    duplicate_line_count:int
    ignored_line_count:int
    unmatched_ledger_count:int
    status:str
    reconciled_by_name:str
    note:str|None
    created_at:datetime

@router.post("",response_model=SnapshotRead,status_code=201)
def create_snapshot(company_id:UUID,account_id:UUID,payload:SnapshotCreate,db:Session=Depends(get_db)):
    try:
        row=create_reconciliation_snapshot(db,company_id=company_id,bank_account_id=account_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("",response_model=list[SnapshotRead])
def list_snapshots(company_id:UUID,account_id:UUID,limit:int=Query(default=50,ge=1,le=200),db:Session=Depends(get_db)):
    return list(db.scalars(select(BankReconciliationSnapshot).where(
        BankReconciliationSnapshot.company_id==company_id,
        BankReconciliationSnapshot.bank_account_id==account_id
    ).order_by(BankReconciliationSnapshot.created_at.desc()).limit(limit)).all())
