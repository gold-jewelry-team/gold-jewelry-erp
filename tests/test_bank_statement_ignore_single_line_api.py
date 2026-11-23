from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatementLine
from app.models.company import Company
from app.routers import bank_reconciliation


def test_ignore_targets_one_statement_line_in_multi_line_import():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="IGNORE-LINE-API", name="銀行對帳忽略明細測試")
    db.add(company)
    db.flush()
    account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="8899",
        currency_code="TWD",
        opening_balance=Decimal("0.00"),
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
                "2026-11-23,銀行手續費,20.00,OUT,FEE-01\n"
                "2026-11-23,存款,500.00,IN,DEP-01\n"
            ),
            "source_file_name": "two-lines.csv",
            "imported_by_name": "店員甲",
        })
        assert imported.status_code == 201, imported.text
        import_id = imported.json()["id"]

        lines_response = client.get(f"{root}/{import_id}/lines")
        assert lines_response.status_code == 200, lines_response.text
        lines = lines_response.json()
        assert len(lines) == 2
        target = next(row for row in lines if row["description"] == "銀行手續費")
        untouched = next(row for row in lines if row["description"] == "存款")

        ignored = client.post(
            f"{root}/{import_id}/lines/{target['id']}/ignore"
        )
        assert ignored.status_code == 200, ignored.text
        assert ignored.json()["id"] == target["id"]
        assert ignored.json()["status"] == "IGNORED"

        refreshed = client.get(f"{root}/{import_id}/lines")
        statuses = {row["id"]: row["status"] for row in refreshed.json()}
        assert statuses[target["id"]] == "IGNORED"
        assert statuses[untouched["id"]] == "UNMATCHED"

        verify = TestSession()
        stored = verify.query(BankStatementLine).filter_by(import_id=import_id).all()
        assert len(stored) == 2
        assert sum(row.status == "IGNORED" for row in stored) == 1
        assert sum(row.status == "UNMATCHED" for row in stored) == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
