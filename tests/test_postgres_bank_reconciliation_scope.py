"""PostgreSQL integration tests for database-enforced reconciliation ownership scopes."""
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.company import Company
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


def _account(company_id, suffix):
    return BankAccount(
        company_id=company_id,
        bank_name="測試銀行",
        account_name=f"測試帳戶{suffix}",
        account_last4=f"{int(suffix) % 10000:04d}",
        currency_code="TWD",
        opening_balance=Decimal("0.00"),
        opening_balance_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def _line(batch, company_id, account_id, *, duplicate_of=None, matched_tx=None):
    return BankStatementLine(
        import_id=batch.id,
        company_id=company_id,
        bank_account_id=account_id,
        transaction_date=date(2026, 11, 19),
        description="PostgreSQL constraint test",
        amount=Decimal("9.00"),
        direction="IN",
        reference_no="PG-CONSTRAINT-001",
        fingerprint=uuid4().hex,
        status="DUPLICATE" if duplicate_of else ("MATCHED" if matched_tx else "UNMATCHED"),
        duplicate_of_line_id=duplicate_of,
        matched_bank_transaction_id=matched_tx,
    )


def _transaction(company_id, account_id, *, statement_line_id=None):
    return BankTransaction(
        company_id=company_id,
        bank_account_id=account_id,
        site_id=None,
        statement_line_id=statement_line_id,
        transaction_type="INTEREST_IN",
        direction="IN",
        amount=Decimal("9.00"),
        currency_code="TWD",
        reference_no="PG-CONSTRAINT-001",
        description="PostgreSQL constraint test",
        created_by_name="integration-test",
        occurred_at=datetime(2026, 11, 19, 12, tzinfo=timezone.utc),
    )


def _assert_rejected_by_database(session, record):
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(record)
            session.flush()


def test_postgres_enforces_company_and_account_scope_foreign_keys():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        suffix = uuid4().hex[:10]
        company_a = Company(code=f"PA{suffix}", name="PostgreSQL Company A")
        company_b = Company(code=f"PB{suffix}", name="PostgreSQL Company B")
        db.add_all([company_a, company_b])
        db.flush()

        account_a1 = _account(company_a.id, 101)
        account_a2 = _account(company_a.id, 102)
        account_b = _account(company_b.id, 201)
        db.add_all([account_a1, account_a2, account_b])
        db.flush()

        batch_a1 = BankStatementImport(
            company_id=company_a.id,
            bank_account_id=account_a1.id,
            source_file_name="a1.csv",
            row_count=1,
            status="IMPORTED",
            imported_by_name="integration-test",
        )
        batch_a2 = BankStatementImport(
            company_id=company_a.id,
            bank_account_id=account_a2.id,
            source_file_name="a2.csv",
            row_count=1,
            status="IMPORTED",
            imported_by_name="integration-test",
        )
        db.add_all([batch_a1, batch_a2])
        db.flush()

        line_a1 = _line(batch_a1, company_a.id, account_a1.id)
        line_a2 = _line(batch_a2, company_a.id, account_a2.id)
        db.add_all([line_a1, line_a2])
        db.flush()

        tx_a2 = _transaction(company_a.id, account_a2.id)
        tx_b = _transaction(company_b.id, account_b.id)
        db.add_all([tx_a2, tx_b])
        db.flush()

        # An import cannot claim an account owned by another company.
        _assert_rejected_by_database(
            db,
            BankStatementImport(
                company_id=company_a.id,
                bank_account_id=account_b.id,
                source_file_name="wrong-company.csv",
                row_count=0,
                status="IMPORTED",
                imported_by_name="integration-test",
            ),
        )

        # A statement line must match the exact account and company of its batch.
        _assert_rejected_by_database(
            db,
            _line(batch_a1, company_a.id, account_a2.id),
        )

        # Duplicate links cannot cross bank-account boundaries.
        _assert_rejected_by_database(
            db,
            _line(batch_a2, company_a.id, account_a2.id, duplicate_of=line_a1.id),
        )

        # A matched transaction must belong to the same account as its statement line.
        _assert_rejected_by_database(
            db,
            _line(batch_a1, company_a.id, account_a1.id, matched_tx=tx_a2.id),
        )

        # A transaction's statement_line_id must point to a line in its own account.
        _assert_rejected_by_database(
            db,
            _transaction(company_a.id, account_a2.id, statement_line_id=line_a1.id),
        )

        # Company boundaries are enforced too, not only account boundaries.
        _assert_rejected_by_database(
            db,
            _transaction(company_b.id, account_b.id, statement_line_id=line_a1.id),
        )
    finally:
        db.rollback()
        db.close()
        engine.dispose()
