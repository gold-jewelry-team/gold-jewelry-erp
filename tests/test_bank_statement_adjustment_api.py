from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementLine
from app.models.company import Company
from app.routers import bank_reconciliation


def test_bank_statement_fee_adjustment_api_creates_linked_ledger_entry():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BANK-ADJ-API", name="銀行調整 API 測試")
    db.add(company)
    db.flush()
    account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="7788",
        currency_code="TWD",
        opening_balance=Decimal("1000.00"),
        opening_balance_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.commit()
    company_id, account_id = company.id, account.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[bank_reconciliation.get_db] = override_db
    try:
        client = TestClient(app)
        root = f"/companies/{company_id}/bank-accounts/{account_id}/statement-imports"
        imported = client.post(root, json={
            "csv_content": (
                "transaction_date,description,amount,direction,reference_no\n"
                "2026-11-23,銀行手續費,25.00,OUT,FEE-API-001\n"
            ),
            "source_file_name": "fee.csv",
            "imported_by_name": "店員甲",
        })
        assert imported.status_code == 201, imported.text
        import_id = imported.json()["id"]
        lines = client.get(f"{root}/{import_id}/lines")
        assert lines.status_code == 200, lines.text
        line_id = lines.json()[0]["id"]
        assert lines.json()[0]["status"] == "UNMATCHED"

        adjustment = client.post(
            f"{root}/{import_id}/lines/{line_id}/adjustment",
            json={
                "transaction_type": "BANK_FEE",
                "created_by_name": "店員甲",
                "reason": "銀行月結手續費",
            },
        )
        assert adjustment.status_code == 201, adjustment.text
        assert adjustment.json()["statement_line_id"] == line_id

        refreshed = client.get(f"{root}/{import_id}/lines")
        line = refreshed.json()[0]
        assert line["status"] == "MATCHED"
        assert line["matched_bank_transaction_id"] == adjustment.json()["id"]

        verify = TestSession()
        ledger = verify.get(BankTransaction, UUID(adjustment.json()["id"]))
        assert ledger is not None
        assert ledger.transaction_type == "BANK_FEE"
        assert ledger.direction == "OUT"
        assert ledger.amount == Decimal("25.00")
        assert ledger.statement_line_id == UUID(line_id)
        assert verify.query(BankStatementLine).filter_by(status="MATCHED").count() == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
