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


def test_one_bank_ledger_transaction_cannot_be_matched_to_two_statement_lines():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BANK-ONE-MATCH", name="銀行流水唯一配對測試")
    db.add(company)
    db.flush()
    account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="6611",
        currency_code="TWD",
        opening_balance=Decimal("0.00"),
        opening_balance_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.flush()
    ledger = BankTransaction(
        company_id=company.id,
        bank_account_id=account.id,
        transaction_type="CASH_DEPOSIT",
        direction="IN",
        amount=Decimal("800.00"),
        currency_code="TWD",
        description="銀行流水原始摘要",
        created_by_name="測試",
        occurred_at=datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc),
    )
    db.add(ledger)
    db.commit()
    company_id, account_id, ledger_id = company.id, account.id, ledger.id
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
                "transaction_date,description,amount,direction\n"
                "2026-11-23,對帳摘要甲,800.00,IN\n"
                "2026-11-23,對帳摘要乙,800.00,IN\n"
            ),
            "source_file_name": "two-candidates.csv",
            "imported_by_name": "店員甲",
        })
        assert imported.status_code == 201, imported.text
        import_id = imported.json()["id"]
        lines = client.get(f"{root}/{import_id}/lines").json()
        assert len(lines) == 2
        assert all(row["status"] == "UNMATCHED" for row in lines)

        first = client.post(
            f"{root}/{import_id}/lines/{lines[0]['id']}/match",
            json={"bank_transaction_id": str(ledger_id)},
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "MATCHED"

        second = client.post(
            f"{root}/{import_id}/lines/{lines[1]['id']}/match",
            json={"bank_transaction_id": str(ledger_id)},
        )
        assert second.status_code == 422
        assert "已被其他對帳明細配對" in second.json()["detail"]

        refreshed = client.get(f"{root}/{import_id}/lines").json()
        statuses = {row["id"]: row["status"] for row in refreshed}
        assert statuses[lines[0]["id"]] == "MATCHED"
        assert statuses[lines[1]["id"]] == "UNMATCHED"
        assert refreshed[0]["matched_bank_transaction_id"] == str(ledger_id) or refreshed[1]["matched_bank_transaction_id"] == str(ledger_id)

        verify = TestSession()
        matched = verify.query(BankStatementLine).filter_by(
            matched_bank_transaction_id=UUID(str(ledger_id))
        ).all()
        assert len(matched) == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
