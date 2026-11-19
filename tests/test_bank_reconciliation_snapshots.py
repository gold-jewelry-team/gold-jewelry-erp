from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import models
from app.db.base import Base
from app.models.company import Company
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.services.bank_reconciliation_snapshots import create_reconciliation_snapshot

def setup_db():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="SNAP",name="對帳快照測試"); db.add(company); db.flush()
    account=BankAccount(company_id=company.id,bank_name="測試銀行",account_name="測試帳戶",
        account_last4="1234",currency_code="TWD",opening_balance=Decimal("1000.00"),
        opening_balance_at=datetime(2026,11,1,tzinfo=timezone.utc)); db.add(account); db.flush()
    batch=BankStatementImport(company_id=company.id,bank_account_id=account.id,
        source_file_name="statement.csv",row_count=1,status="IMPORTED",imported_by_name="測試")
    db.add(batch); db.flush()
    tx=BankTransaction(company_id=company.id,bank_account_id=account.id,transaction_type="CASH_DEPOSIT",
        direction="IN",amount=Decimal("500.00"),currency_code="TWD",reference_no="R1",
        description="存款",created_by_name="測試",occurred_at=datetime(2026,11,19,3,tzinfo=timezone.utc))
    db.add(tx); db.flush()
    line=BankStatementLine(import_id=batch.id,company_id=company.id,bank_account_id=account.id,
        transaction_date=date(2026,11,19),description="存款",amount=Decimal("500.00"),
        direction="IN",reference_no="R1",fingerprint="a"*64,status="MATCHED",
        matched_bank_transaction_id=tx.id)
    db.add(line); db.commit()
    return engine,db,company,account,batch

def test_reconciliation_snapshot_reconciled_when_balances_and_matches_agree():
    engine,db,company,account,batch=setup_db()
    row=create_reconciliation_snapshot(db,company_id=company.id,bank_account_id=account.id,
        import_id=batch.id,period_start=date(2026,11,19),period_end=date(2026,11,19),
        statement_opening_balance=Decimal("1000.00"),statement_closing_balance=Decimal("1500.00"),
        reconciled_by_name="覆核人")
    db.commit()
    assert row.status=="RECONCILED"
    assert row.statement_net_movement==Decimal("500.00")
    assert row.ledger_net_movement==Decimal("500.00")
    assert row.net_difference==Decimal("0.00")
    assert row.unmatched_ledger_count==0
    engine.dispose()

def test_reconciliation_snapshot_flags_unmatched_and_balance_difference():
    engine,db,company,account,batch=setup_db()
    extra=BankTransaction(company_id=company.id,bank_account_id=account.id,transaction_type="CASH_WITHDRAWAL",
        direction="OUT",amount=Decimal("100.00"),currency_code="TWD",description="提款",
        created_by_name="測試",occurred_at=datetime(2026,11,19,4,tzinfo=timezone.utc))
    db.add(extra); db.commit()
    row=create_reconciliation_snapshot(db,company_id=company.id,bank_account_id=account.id,
        import_id=batch.id,period_start=date(2026,11,19),period_end=date(2026,11,19),
        statement_opening_balance=Decimal("1000.00"),statement_closing_balance=Decimal("1400.00"),
        reconciled_by_name="覆核人")
    db.commit()
    assert row.status=="NEEDS_REVIEW"
    assert row.net_difference==Decimal("100.00")
    assert row.unmatched_ledger_count==1
    engine.dispose()
