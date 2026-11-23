from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.daily_closing import DailyClosing
from app.models.operating_expense import OperatingExpense
from app.models.site import Site
from app.routers import daily_closing, expenses


def _expense_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    company = Company(code="EXP-IDEMP", name="費用重送測試銀樓")
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
    app.dependency_overrides[expenses.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    return engine, test_session, company_id, site_id


def _expense_payload(site_id, expense_no="EXP-IDEMP-001", amount="1200.00"):
    return {
        "site_id": str(site_id),
        "expense_no": expense_no,
        "expense_date": "2026-11-23",
        "category_code": "UTILITIES",
        "description": "店面水電費",
        "amount": amount,
        "payee": "台電",
        "payment_method": None,
        "receipt_no": "INV-EXP-001",
        "note": "11 月電費",
    }


def test_expense_create_replay_returns_original_record_and_rejects_changed_content():
    engine, TestSession, company_id, site_id = _expense_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/operating-expenses"
        payload = _expense_payload(site_id)

        first = client.post(base, json=payload)
        replay = client.post(base, json=payload)

        assert first.status_code == 201, first.text
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["status"] == "UNPAID"

        changed = client.post(base, json={**payload, "amount": "1300.00"})
        assert changed.status_code == 409, changed.text
        assert "不同的費用內容" in changed.json()["detail"]

        verify = TestSession()
        rows = verify.scalars(select(OperatingExpense).where(
            OperatingExpense.company_id == company_id
        )).all()
        assert len(rows) == 1
        assert rows[0].amount == Decimal("1200.00")
        assert rows[0].status == "UNPAID"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_expense_payment_retry_after_daily_close_returns_paid_record_once():
    engine, TestSession, company_id, site_id = _expense_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/operating-expenses"
        created = client.post(base, json=_expense_payload(site_id, "EXP-PAY-RETRY-001"))
        assert created.status_code == 201, created.text
        expense_id = created.json()["id"]
        payment_payload = {"payment_method": "TRANSFER"}

        first = client.post(f"{base}/{expense_id}/pay", json=payment_payload)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "PAID"

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        assert closing.json()["expenses_paid_amount"] == "1200.00"
        assert closing.json()["net_cash_flow"] == "-1200.00"

        # The first payment committed even if its response was lost. The exact
        # retry must return the original row before the daily-close guard.
        replay = client.post(f"{base}/{expense_id}/pay", json=payment_payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["paid_at"] == first.json()["paid_at"]
        assert replay.json()["payment_method"] == "TRANSFER"

        changed_method = client.post(
            f"{base}/{expense_id}/pay", json={"payment_method": "CASH"}
        )
        assert changed_method.status_code == 409, changed_method.text

        verify = TestSession()
        row = verify.get(OperatingExpense, UUID(expense_id))
        assert row.status == "PAID"
        assert row.payment_method == "TRANSFER"
        count = verify.scalar(select(func.count()).select_from(OperatingExpense).where(
            OperatingExpense.company_id == company_id
        ))
        closings = verify.scalar(select(func.count()).select_from(DailyClosing).where(
            DailyClosing.company_id == company_id
        ))
        assert count == 1
        assert closings == 1
        assert row.paid_at is not None
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_delayed_unpaid_expense_create_replay_returns_record_after_payment_and_close():
    engine, TestSession, company_id, site_id = _expense_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/operating-expenses"
        payload = _expense_payload(site_id, "EXP-CREATE-DELAYED-001")
        first = client.post(base, json=payload)
        assert first.status_code == 201, first.text
        expense_id = first.json()["id"]

        paid = client.post(
            f"{base}/{expense_id}/pay",
            json={"payment_method": "CASH"},
        )
        assert paid.status_code == 200, paid.text

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text

        delayed_replay = client.post(base, json=payload)
        assert delayed_replay.status_code == 200, delayed_replay.text
        assert delayed_replay.json()["id"] == first.json()["id"]
        assert delayed_replay.json()["status"] == "PAID"
        assert delayed_replay.json()["payment_method"] == "CASH"

        verify = TestSession()
        rows = verify.scalars(select(OperatingExpense).where(
            OperatingExpense.company_id == company_id
        )).all()
        assert len(rows) == 1
        assert rows[0].amount == Decimal("1200.00")
        assert rows[0].status == "PAID"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
