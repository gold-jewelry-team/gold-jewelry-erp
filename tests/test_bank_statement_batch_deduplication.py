from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db.base import Base
from app.models.company import Company
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementLine
from app.services.bank_reconciliation import import_bank_statement_csv


def _setup():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    company = Company(code="BATCH", name="同批次重複匯入測試")
    db.add(company)
    db.flush()
    account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="1234",
        currency_code="TWD",
        opening_balance=Decimal("1000.00"),
        opening_balance_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    db.add(account)
    db.flush()
    transaction = BankTransaction(
        company_id=company.id,
        bank_account_id=account.id,
        transaction_type="INTEREST_IN",
        direction="IN",
        amount=Decimal("5.00"),
        currency_code="TWD",
        reference_no="INT-001",
        description="活存利息",
        created_by_name="測試",
        occurred_at=datetime(2026, 11, 19, 3, tzinfo=timezone.utc),
    )
    db.add(transaction)
    db.commit()
    return engine, db, company, account, transaction


def test_import_marks_repeated_rows_in_same_csv_as_duplicate_and_matches_once():
    engine, db, company, account, transaction = _setup()
    csv_content = (
        "transaction_date,description,amount,direction,reference_no\\n"
        "2026-11-19,活存利息,5.00,IN,INT-001\\n"
        "2026-11-19,活存利息,5.00,IN,INT-001\\n"
    )

    batch = import_bank_statement_csv(
        db,
        company_id=company.id,
        bank_account_id=account.id,
        csv_content=csv_content,
        source_file_name="same-batch.csv",
        imported_by_name="測試人員",
    )
    db.commit()

    lines = list(db.scalars(
        select(BankStatementLine).where(BankStatementLine.import_id == batch.id)
    ).all())
    assert len(lines) == 2
    matched = [line for line in lines if line.status == "MATCHED"]
    duplicates = [line for line in lines if line.status == "DUPLICATE"]
    assert len(matched) == 1
    assert len(duplicates) == 1
    assert matched[0].matched_bank_transaction_id == transaction.id
    assert duplicates[0].duplicate_of_line_id == matched[0].id

    # A later import must also handle multiple historical rows with this fingerprint.
    next_batch = import_bank_statement_csv(
        db,
        company_id=company.id,
        bank_account_id=account.id,
        csv_content=csv_content.splitlines()[0] + "\\n" + csv_content.splitlines()[1] + "\\n",
        source_file_name="later-import.csv",
        imported_by_name="測試人員",
    )
    db.commit()
    later_line = db.scalar(
        select(BankStatementLine).where(BankStatementLine.import_id == next_batch.id)
    )
    assert later_line is not None
    assert later_line.status == "DUPLICATE"
    assert later_line.duplicate_of_line_id is not None
    engine.dispose()
