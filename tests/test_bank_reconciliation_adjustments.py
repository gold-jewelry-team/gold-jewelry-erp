from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import models
from app.db.base import Base
from app.models.company import Company
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.services.bank_reconciliation import create_statement_adjustment

def _setup():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="ADJ",name="銀行調整測試"); db.add(company); db.flush()
    account=BankAccount(company_id=company.id,bank_name="測試銀行",account_name="營運帳戶",
        account_last4="1234",currency_code="TWD",opening_balance=Decimal("1000.00"),
        opening_balance_at=datetime(2026,11,1,tzinfo=timezone.utc)); db.add(account); db.flush()
    batch=BankStatementImport(company_id=company.id,bank_account_id=account.id,
        source_file_name="bank.csv",row_count=1,status="IMPORTED",imported_by_name="測試"); db.add(batch); db.flush()
    line=BankStatementLine(import_id=batch.id,company_id=company.id,bank_account_id=account.id,
        transaction_date=date(2026,11,19),description="銀行手續費",amount=Decimal("20.00"),
        direction="OUT",reference_no="FEE-01",fingerprint="f"*64,status="UNMATCHED")
    db.add(line); db.commit()
    return engine,db,company,account,batch,line

def test_statement_fee_adjustment_creates_linked_ledger_and_matches_line():
    engine,db,company,account,batch,line=_setup()
    tx=create_statement_adjustment(db,company_id=company.id,import_id=batch.id,line_id=line.id,
        transaction_type="BANK_FEE",created_by_name="店員甲",reason="銀行月結手續費")
    db.commit()
    assert tx.transaction_type=="BANK_FEE" and tx.direction=="OUT"
    assert tx.amount==Decimal("20.00")
    assert tx.statement_line_id==line.id
    assert line.status=="MATCHED" and line.matched_bank_transaction_id==tx.id
    engine.dispose()

def test_statement_adjustment_rejects_wrong_direction_and_duplicate():
    engine,db,company,account,batch,line=_setup()
    with pytest.raises(ValueError,match="支出"):
        create_statement_adjustment(db,company_id=company.id,import_id=batch.id,line_id=line.id,
            transaction_type="INTEREST_IN",created_by_name="店員甲",reason="錯誤類型")
    tx=create_statement_adjustment(db,company_id=company.id,import_id=batch.id,line_id=line.id,
        transaction_type="BANK_FEE",created_by_name="店員甲",reason="月結手續費")
    db.flush()
    with pytest.raises(ValueError,match="未配對"):
        create_statement_adjustment(db,company_id=company.id,import_id=batch.id,line_id=line.id,
            transaction_type="BANK_FEE",created_by_name="店員甲",reason="重複調整")
    engine.dispose()
