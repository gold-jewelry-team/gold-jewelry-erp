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
from app.models.bank_reconciliation import BankReconciliationSnapshot
from app.services.bank_reconciliation_reports import build_bank_reconciliation_report

def setup_report_db():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="RPT",name="報表測試");db.add(company);db.flush()
    account=BankAccount(company_id=company.id,bank_name="測試銀行",account_name="營運帳戶",
        account_last4="1234",currency_code="TWD",opening_balance=Decimal("1000.00"),
        opening_balance_at=datetime(2026,11,1,tzinfo=timezone.utc));db.add(account);db.flush()
    batch=BankStatementImport(company_id=company.id,bank_account_id=account.id,
        source_file_name="bank.csv",row_count=2,status="IMPORTED",imported_by_name="測試");db.add(batch);db.flush()
    fee=BankTransaction(company_id=company.id,bank_account_id=account.id,transaction_type="BANK_FEE",
        direction="OUT",amount=Decimal("20.00"),currency_code="TWD",description="銀行手續費",
        created_by_name="店員",occurred_at=datetime(2026,11,19,3,tzinfo=timezone.utc),note="月結費用")
    interest=BankTransaction(company_id=company.id,bank_account_id=account.id,transaction_type="INTEREST_IN",
        direction="IN",amount=Decimal("5.00"),currency_code="TWD",description="利息",
        created_by_name="店員",occurred_at=datetime(2026,11,19,4,tzinfo=timezone.utc),note="活存利息")
    db.add_all([fee,interest]);db.flush()
    db.add_all([
        BankStatementLine(import_id=batch.id,company_id=company.id,bank_account_id=account.id,
            transaction_date=date(2026,11,19),description="銀行手續費",amount=Decimal("20.00"),
            direction="OUT",fingerprint="a"*64,status="MATCHED",matched_bank_transaction_id=fee.id),
        BankStatementLine(import_id=batch.id,company_id=company.id,bank_account_id=account.id,
            transaction_date=date(2026,11,19),description="利息",amount=Decimal("5.00"),
            direction="IN",fingerprint="b"*64,status="MATCHED",matched_bank_transaction_id=interest.id),
    ])
    db.commit()
    return engine,db,company,account

def test_report_summarizes_statuses_amounts_adjustments_and_snapshot():
    engine,db,company,account=setup_report_db()
    snap=BankReconciliationSnapshot(company_id=company.id,bank_account_id=account.id,
        import_id=db.query(BankStatementImport).one().id,period_start=date(2026,11,19),
        period_end=date(2026,11,19),statement_opening_balance=Decimal("1000"),
        statement_closing_balance=Decimal("985"),statement_net_movement=Decimal("-15"),
        ledger_net_movement=Decimal("-15"),balance_difference=Decimal("0"),
        net_difference=Decimal("0"),statement_line_count=2,matched_line_count=2,
        unmatched_line_count=0,duplicate_line_count=0,ignored_line_count=0,
        unmatched_ledger_count=0,status="RECONCILED",reconciled_by_name="覆核人")
    db.add(snap);db.commit()
    result=build_bank_reconciliation_report(db,company_id=company.id,bank_account_id=account.id,
        period_start=date(2026,11,19),period_end=date(2026,11,19))
    assert result["statement_line_count"]==2
    assert result["status_counts"]["MATCHED"]==2
    assert result["statement_net_amount"]==Decimal("-15.00")
    assert result["adjustments"][0]["out_amount"]==Decimal("20.00")
    assert result["adjustments"][1]["in_amount"]==Decimal("5.00")
    assert result["latest_snapshot"]["status"]=="RECONCILED"
    engine.dispose()

def test_report_rejects_invalid_period_and_unknown_account():
    engine,db,company,account=setup_report_db()
    with pytest.raises(ValueError,match="結束日"):
        build_bank_reconciliation_report(db,company_id=company.id,bank_account_id=account.id,
            period_start=date(2026,11,20),period_end=date(2026,11,19))
    engine.dispose()
