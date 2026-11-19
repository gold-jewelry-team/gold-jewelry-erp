"""Real PostgreSQL integration tests for bank reconciliation scope checks."""
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.company import Company
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.services.bank_reconciliation import _fingerprint, import_bank_statement_csv


DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.mark.parametrize("scope", ["company", "bank_account"])
def test_postgres_rejects_cross_scope_duplicate_chain(scope):
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        suffix = uuid4().hex[:12]
        company = Company(code=f"PG{suffix}", name="PostgreSQL scope test")
        db.add(company)
        db.flush()

        target_account = BankAccount(
            company_id=company.id,
            bank_name="測試銀行",
            account_name="目標帳戶",
            account_last4="1234",
            currency_code="TWD",
            opening_balance=Decimal("0.00"),
            opening_balance_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        db.add(target_account)
        db.flush()

        if scope == "company":
            foreign_company = Company(code=f"PF{suffix}", name="Foreign company")
            db.add(foreign_company)
            db.flush()
            foreign_company_id = foreign_company.id
        else:
            foreign_company_id = company.id

        foreign_account = BankAccount(
            company_id=foreign_company_id,
            bank_name="其他銀行",
            account_name="來源帳戶",
            account_last4="5678",
            currency_code="TWD",
            opening_balance=Decimal("0.00"),
            opening_balance_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        db.add(foreign_account)
        db.flush()

        target_batch = BankStatementImport(
            company_id=company.id,
            bank_account_id=target_account.id,
            source_file_name="target.csv",
            row_count=1,
            status="IMPORTED",
            imported_by_name="integration-test",
        )
        foreign_batch = BankStatementImport(
            company_id=foreign_company_id,
            bank_account_id=foreign_account.id,
            source_file_name="foreign.csv",
            row_count=1,
            status="IMPORTED",
            imported_by_name="integration-test",
        )
        db.add_all([target_batch, foreign_batch])
        db.flush()

        fingerprint = _fingerprint(
            date(2026, 11, 19),
            "PostgreSQL scope",
            Decimal("9.00"),
            "IN",
            "PG-SCOPE-001",
        )
        foreign_root = BankStatementLine(
            import_id=foreign_batch.id,
            company_id=foreign_company_id,
            bank_account_id=foreign_account.id,
            transaction_date=date(2026, 11, 19),
            description="PostgreSQL scope",
            amount=Decimal("9.00"),
            direction="IN",
            reference_no="PG-SCOPE-001",
            fingerprint=fingerprint,
            status="UNMATCHED",
        )
        db.add(foreign_root)
        db.flush()

        malformed_duplicate = BankStatementLine(
            import_id=target_batch.id,
            company_id=company.id,
            bank_account_id=target_account.id,
            transaction_date=date(2026, 11, 19),
            description="PostgreSQL scope",
            amount=Decimal("9.00"),
            direction="IN",
            reference_no="PG-SCOPE-001",
            fingerprint=fingerprint,
            status="DUPLICATE",
            duplicate_of_line_id=foreign_root.id,
        )
        db.add(malformed_duplicate)
        db.flush()

        csv_content = (
            "transaction_date,description,amount,direction,reference_no\\n"
            "2026-11-19,PostgreSQL scope,9.00,IN,PG-SCOPE-001\\n"
        )
        with pytest.raises(ValueError, match="跨越公司或銀行帳戶"):
            import_bank_statement_csv(
                db,
                company_id=company.id,
                bank_account_id=target_account.id,
                csv_content=csv_content,
                source_file_name="postgres-scope.csv",
                imported_by_name="integration-test",
            )
    finally:
        db.rollback()
        db.close()
        engine.dispose()
