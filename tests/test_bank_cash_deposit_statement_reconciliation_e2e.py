from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankTransaction
from app.models.bank_statement import BankStatementLine
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.company import Company
from app.models.site import Site
from app.routers import bank_accounts, bank_reconciliation


def test_cash_deposit_links_bank_ledger_cash_drawer_and_imported_statement_line():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BANK-CASH-RECON", name="銀行存款對帳整合測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[bank_accounts.get_db] = override_db
    app.dependency_overrides[bank_reconciliation.get_db] = override_db
    try:
        client = TestClient(app)
        bank_base = f"/companies/{company_id}/bank-accounts"
        account = client.post(
            bank_base,
            json={
                "bank_name": "測試銀行",
                "account_name": "營運帳戶",
                "account_last4": "7788",
                "opening_balance": "10000.00",
                "opening_balance_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]

        deposit = client.post(
            f"{bank_base}/{account_id}/cash-deposits",
            json={
                "site_id": str(site_id),
                "amount": "1500.00",
                "created_by_name": "店員甲",
                "reference_no": "CASH-DEP-251",
            },
        )
        assert deposit.status_code == 201, deposit.text
        bank_transaction_id = deposit.json()["id"]
        assert deposit.json()["direction"] == "IN"
        assert deposit.json()["transaction_type"] == "CASH_DEPOSIT"

        transaction_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date().isoformat()
        csv_content = (
            "transaction_date,description,amount,direction,reference_no\n"
            f"{transaction_date},現金存入銀行,1500.00,IN,CASH-DEP-251\n"
        )
        imported = client.post(
            f"{bank_base}/{account_id}/statement-imports",
            json={
                "csv_content": csv_content,
                "source_file_name": "bank-cash-deposit.csv",
                "imported_by_name": "會計甲",
            },
        )
        assert imported.status_code == 201, imported.text
        import_id = imported.json()["id"]

        lines = client.get(
            f"{bank_base}/{account_id}/statement-imports/{import_id}/lines"
        )
        assert lines.status_code == 200, lines.text
        assert len(lines.json()) == 1
        line = lines.json()[0]
        assert line["status"] == "MATCHED"
        assert line["matched_bank_transaction_id"] == bank_transaction_id

        verify = TestSession()
        bank_tx = verify.get(BankTransaction, UUID(bank_transaction_id))
        assert bank_tx is not None
        drawer = verify.query(CashDrawerMovement).one()
        statement_line = verify.query(BankStatementLine).one()
        assert bank_tx.direction == "IN"
        assert bank_tx.amount == 1500
        assert drawer.direction == "OUT"
        assert drawer.amount == 1500
        assert drawer.bank_transaction_id == bank_tx.id
        assert statement_line.matched_bank_transaction_id == bank_tx.id
        verify.close()

        accounts = client.get(bank_base)
        assert accounts.status_code == 200, accounts.text
        current = next(
            row for row in accounts.json()
            if row["account"]["id"] == account_id
        )
        assert current["current_balance"] == "11500.00"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
