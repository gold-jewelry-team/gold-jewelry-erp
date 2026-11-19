"""Bank statement import and reconciliation APIs."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.services.bank_reconciliation import import_bank_statement_csv, match_statement_line, ignore_statement_line

router=APIRouter(prefix="/companies/{company_id}/bank-accounts/{account_id}/statement-imports",tags=["bank reconciliation"])
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

class StatementImportCreate(BaseModel):
    csv_content:str=Field(min_length=1)
    source_file_name:str=Field(default="statement.csv",max_length=200)
    imported_by_name:str=Field(min_length=1,max_length=120)

class StatementImportRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    company_id:UUID
    bank_account_id:UUID
    source_file_name:str
    row_count:int
    status:str
    imported_by_name:str
    created_at:datetime

class StatementLineRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    import_id:UUID
    company_id:UUID
    bank_account_id:UUID
    transaction_date:object
    description:str
    amount:object
    direction:str
    reference_no:str|None
    status:str
    matched_bank_transaction_id:UUID|None
    duplicate_of_line_id:UUID|None

class MatchCreate(BaseModel):
    bank_transaction_id:UUID

class ActionResult(BaseModel):
    id:UUID
    status:str
    matched_bank_transaction_id:UUID|None

@router.post("",response_model=StatementImportRead,status_code=201)
def create_import(company_id:UUID,account_id:UUID,payload:StatementImportCreate,db:Session=Depends(get_db)):
    try:
        row=import_bank_statement_csv(db,company_id=company_id,bank_account_id=account_id,**payload.model_dump())
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("",response_model=list[StatementImportRead])
def list_imports(company_id:UUID,account_id:UUID,limit:int=Query(default=50,ge=1,le=200),db:Session=Depends(get_db)):
    return list(db.scalars(select(BankStatementImport).where(
        BankStatementImport.company_id==company_id,BankStatementImport.bank_account_id==account_id
    ).order_by(BankStatementImport.created_at.desc()).limit(limit)).all())

@router.get("/{import_id}/lines",response_model=list[StatementLineRead])
def list_lines(company_id:UUID,account_id:UUID,import_id:UUID,status:str|None=None,db:Session=Depends(get_db)):
    q=select(BankStatementLine).where(BankStatementLine.company_id==company_id,
        BankStatementLine.bank_account_id==account_id,BankStatementLine.import_id==import_id)
    if status:
        if status not in {"UNMATCHED","MATCHED","DUPLICATE","IGNORED"}:
            raise HTTPException(status_code=422,detail="不支援的對帳狀態。")
        q=q.where(BankStatementLine.status==status)
    return list(db.scalars(q.order_by(BankStatementLine.transaction_date,BankStatementLine.id)).all())

@router.post("/{import_id}/lines/{line_id}/match",response_model=ActionResult)
def post_match(company_id:UUID,account_id:UUID,import_id:UUID,line_id:UUID,payload:MatchCreate,db:Session=Depends(get_db)):
    line=db.execute(select(BankStatementLine).where(BankStatementLine.import_id==import_id,
        BankStatementLine.bank_account_id==account_id)).scalar_one_or_none()
    if line is None or line.id!=line_id:
        raise HTTPException(status_code=404,detail="對帳單明細不存在。")
    try:
        row=match_statement_line(db,company_id=company_id,line_id=line_id,bank_transaction_id=payload.bank_transaction_id)
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post("/{import_id}/lines/{line_id}/ignore",response_model=ActionResult)
def post_ignore(company_id:UUID,account_id:UUID,import_id:UUID,line_id:UUID,db:Session=Depends(get_db)):
    line=db.execute(select(BankStatementLine).where(BankStatementLine.import_id==import_id,
        BankStatementLine.bank_account_id==account_id)).scalar_one_or_none()
    if line is None or line.id!=line_id:
        raise HTTPException(status_code=404,detail="對帳單明細不存在。")
    try:
        row=ignore_statement_line(db,company_id=company_id,line_id=line_id)
        db.commit(); db.refresh(row); return row
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=422,detail=str(exc)) from exc
