from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.daily_closing import DailyClosing
from app.models.company import Company
from app.models.site import Site
from app.routers import cash_counts, cash_drawer_movements, daily_closing


def _cash_drawer_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    company = Company(code="DRAWER-IDEMP", name="現金櫃重送測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[cash_drawer_movements.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[cash_counts.get_db] = override_db
    return engine, test_session, company_id, site_id


def test_cash_drawer_movement_retry_is_exactly_once_even_after_daily_close():
    engine, TestSession, company_id, site_id = _cash_drawer_context()
    key = str(uuid4())
    payload = {
        "movement_type": "BANK_DEPOSIT",
        "amount": "400.00",
        "description": "存入銀行",
        "created_by_name": "店員甲",
        "reference_no": "BANK-DEP-RETRY-001",
        "note": "當日存款",
        "idempotency_key": key,
    }
    try:
        client = TestClient(app)
        url = f"/companies/{company_id}/sites/{site_id}/cash-drawer-movements"

        first = client.post(url, json=payload)
        replay = client.post(url, json=payload)

        assert first.status_code == 201, first.text
        assert first.json()["direction"] == "OUT"
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        assert closing.json()["cash_drawer_out_amount"] == "400.00"
        assert closing.json()["cash_drawer_in_amount"] == "0.00"
        assert closing.json()["net_cash_flow"] == "0.00"

        # An exact retry after the daily close must return the original ledger row.
        delayed_replay = client.post(url, json=payload)
        assert delayed_replay.status_code == 200, delayed_replay.text
        assert delayed_replay.json()["id"] == first.json()["id"]

        changed = client.post(url, json={**payload, "amount": "450.00"})
        assert changed.status_code == 409, changed.text
        assert "不同的異動內容" in changed.json()["detail"]

        # New cash drawer movements remain blocked after the business day is closed.
        new_request = client.post(url, json={
            **payload,
            "amount": "50.00",
            "reference_no": "BANK-DEP-RETRY-002",
            "idempotency_key": str(uuid4()),
        })
        assert new_request.status_code == 422, new_request.text

        verify = TestSession()
        rows = verify.scalars(select(CashDrawerMovement).where(
            CashDrawerMovement.company_id == company_id
        )).all()
        closings = verify.scalars(select(DailyClosing).where(
            DailyClosing.company_id == company_id
        )).all()
        assert len(rows) == 1
        assert rows[0].idempotency_key.hex == key.replace("-", "")
        assert rows[0].amount == Decimal("400.00")
        assert rows[0].direction == "OUT"
        assert len(closings) == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_cash_drawer_key_reused_for_different_movement_is_rejected():
    engine, TestSession, company_id, site_id = _cash_drawer_context()
    key = str(uuid4())
    payload = {
        "movement_type": "BANK_WITHDRAWAL",
        "amount": "100.00",
        "description": "銀行提款",
        "created_by_name": "店員甲",
        "reference_no": "BANK-WDR-RETRY-001",
        "idempotency_key": key,
    }
    try:
        client = TestClient(app)
        url = f"/companies/{company_id}/sites/{site_id}/cash-drawer-movements"
        first = client.post(url, json=payload)
        changed = client.post(url, json={
            **payload,
            "movement_type": "BANK_DEPOSIT",
            "amount": "200.00",
        })

        assert first.status_code == 201, first.text
        assert changed.status_code == 409, changed.text
        assert "不同的異動內容" in changed.json()["detail"]

        verify = TestSession()
        count = verify.scalar(select(func.count()).select_from(CashDrawerMovement).where(
            CashDrawerMovement.company_id == company_id
        ))
        rows = verify.scalars(select(CashDrawerMovement).where(
            CashDrawerMovement.company_id == company_id
        )).all()
        assert count == 1
        assert rows[0].movement_type == "BANK_WITHDRAWAL"
        assert rows[0].amount == Decimal("100.00")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
