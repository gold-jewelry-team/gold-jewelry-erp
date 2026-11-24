from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankTransaction
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.company import Company
from app.models.site import Site
from app.routers import bank_accounts, cash_counts, cash_drawer_movements, daily_closing


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as session:
        company = Company(code="BANK-IDEMPOTENCY", name="銀行防重複測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        company_id, site_id = company.id, site.id
        session.commit()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[bank_accounts.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[cash_counts.get_db] = override_db
    app.dependency_overrides[cash_drawer_movements.get_db] = override_db
    return engine, TestSession, company_id, site_id


def _create_account(client, company_id, account_name, last4, opening_balance):
    response = client.post(
        f"/companies/{company_id}/bank-accounts",
        json={
            "bank_name": "測試銀行",
            "account_name": account_name,
            "account_last4": last4,
            "opening_balance": str(opening_balance),
            "opening_balance_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_cash_deposit_and_withdrawal_retries_do_not_duplicate_ledger_or_drawer_rows():
    engine, TestSession, company_id, site_id = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/bank-accounts"
        account_id = _create_account(client, company_id, "營運帳戶", "1234", "10000.00")

        deposit_payload = {
            "site_id": str(site_id),
            "amount": "1500.00",
            "created_by_name": "店員甲",
            "reference_no": "DEP-001",
            "note": "當日營收存款",
            "idempotency_key": str(uuid4()),
        }
        deposit = client.post(f"{base}/{account_id}/cash-deposits", json=deposit_payload)
        assert deposit.status_code == 201, deposit.text
        deposit_retry = client.post(f"{base}/{account_id}/cash-deposits", json=deposit_payload)
        assert deposit_retry.status_code == 200, deposit_retry.text
        assert deposit_retry.json()["id"] == deposit.json()["id"]

        changed_deposit = {**deposit_payload, "amount": "1600.00"}
        conflict = client.post(f"{base}/{account_id}/cash-deposits", json=changed_deposit)
        assert conflict.status_code == 409, conflict.text

        withdrawal_payload = {
            "site_id": str(site_id),
            "amount": "500.00",
            "created_by_name": "店員乙",
            "reference_no": "WD-001",
            "note": "補充現金櫃",
            "idempotency_key": str(uuid4()),
        }
        withdrawal = client.post(
            f"{base}/{account_id}/cash-withdrawals", json=withdrawal_payload
        )
        assert withdrawal.status_code == 201, withdrawal.text
        withdrawal_retry = client.post(
            f"{base}/{account_id}/cash-withdrawals", json=withdrawal_payload
        )
        assert withdrawal_retry.status_code == 200, withdrawal_retry.text
        assert withdrawal_retry.json()["id"] == withdrawal.json()["id"]

        check = TestSession()
        assert check.query(BankTransaction).count() == 2
        assert check.query(CashDrawerMovement).count() == 2
        assert check.query(CashDrawerMovement).filter(
            CashDrawerMovement.bank_transaction_id.is_not(None)
        ).count() == 2
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_bank_account_transfer_retry_returns_original_pair_and_rejects_changed_payload():
    engine, TestSession, company_id, _site_id = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/bank-accounts"
        source_id = _create_account(client, company_id, "營運帳戶", "1234", "10000.00")
        destination_id = _create_account(client, company_id, "備用帳戶", "5678", "2000.00")

        payload = {
            "from_account_id": source_id,
            "to_account_id": destination_id,
            "amount": "1200.00",
            "created_by_name": "管理者",
            "reference_no": "TRF-001",
            "note": "營運資金調撥",
            "idempotency_key": str(uuid4()),
        }
        created = client.post(f"{base}/transfers", json=payload)
        assert created.status_code == 201, created.text
        assert len(created.json()) == 2
        assert created.json()[0]["transfer_group_id"] == created.json()[1]["transfer_group_id"]

        retried = client.post(f"{base}/transfers", json=payload)
        assert retried.status_code == 200, retried.text
        assert [row["id"] for row in retried.json()] == [
            row["id"] for row in created.json()
        ]

        changed = {**payload, "amount": "1300.00"}
        conflict = client.post(f"{base}/transfers", json=changed)
        assert conflict.status_code == 409, conflict.text

        check = TestSession()
        rows = check.query(BankTransaction).all()
        assert len(rows) == 2
        assert {row.transaction_type for row in rows} == {"TRANSFER_OUT", "TRANSFER_IN"}
        assert check.query(CashDrawerMovement).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
