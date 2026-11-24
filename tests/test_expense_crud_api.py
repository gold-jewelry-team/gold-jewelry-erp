from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.site import Site
from app.routers import daily_closing, expenses


@pytest.fixture
def expense_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        company = Company(code="EXP-CRUD", name="費用 CRUD 測試公司")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        db.add(site)
        db.commit()
        company_id, site_id = company.id, site.id

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[expenses.get_db] = override
    app.dependency_overrides[daily_closing.get_db] = override
    try:
        yield TestClient(app), company_id, site_id, Session
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _create_expense(client, company_id, site_id, expense_no, **overrides):
    payload = {
        "site_id": str(site_id),
        "expense_no": expense_no,
        "expense_date": "2026-11-19",
        "category_code": "UTILITIES",
        "description": "水電費",
        "amount": "1200.00",
    }
    payload.update(overrides)
    response = client.post(f"/companies/{company_id}/operating-expenses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_unpaid_expense_can_be_edited_and_voided_but_paid_expense_is_immutable(expense_context):
    client, company_id, site_id, _Session = expense_context
    unpaid = _create_expense(client, company_id, site_id, "EXP-EDIT-001")
    expense_id = unpaid["id"]

    updated = client.patch(
        f"/companies/{company_id}/operating-expenses/{expense_id}",
        json={
            "expense_date": "2026-11-20",
            "category_code": "REPAIR",
            "description": "冷氣維修",
            "amount": "2500.00",
            "payee": "維修廠商",
            "receipt_no": "RCPT-001",
            "note": "已確認報價",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "冷氣維修"
    assert updated.json()["amount"] == "2500.00"
    assert updated.json()["status"] == "UNPAID"

    voided = client.post(f"/companies/{company_id}/operating-expenses/{expense_id}/void")
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "VOID"

    cannot_edit_void = client.patch(
        f"/companies/{company_id}/operating-expenses/{expense_id}",
        json={"description": "不應修改"},
    )
    assert cannot_edit_void.status_code == 409

    paid = _create_expense(
        client, company_id, site_id, "EXP-PAID-001",
        expense_no="EXP-PAID-001",
        payment_method="CASH",
    )
    cannot_edit_paid = client.patch(
        f"/companies/{company_id}/operating-expenses/{paid['id']}",
        json={"description": "不應修改"},
    )
    assert cannot_edit_paid.status_code == 409
    cannot_void_paid = client.post(
        f"/companies/{company_id}/operating-expenses/{paid['id']}/void"
    )
    assert cannot_void_paid.status_code == 409


def test_expense_edit_and_void_respect_daily_closing_and_company_scope(expense_context):
    client, company_id, site_id, _Session = expense_context
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
    expense = _create_expense(
        client, company_id, site_id, "EXP-CLOSED-001",
        expense_date=today.isoformat(),
    )
    closing = client.post(
        f"/companies/{company_id}/sites/{site_id}/daily-closings",
        json={"business_date": today.isoformat()},
    )
    assert closing.status_code == 201, closing.text

    blocked_edit = client.patch(
        f"/companies/{company_id}/operating-expenses/{expense['id']}",
        json={"description": "結帳後不可修改"},
    )
    assert blocked_edit.status_code == 422
    blocked_void = client.post(
        f"/companies/{company_id}/operating-expenses/{expense['id']}/void"
    )
    assert blocked_void.status_code == 422

    foreign = client.patch(
        f"/companies/00000000-0000-0000-0000-000000000001/operating-expenses/{expense['id']}",
        json={"description": "跨公司不應修改"},
    )
    assert foreign.status_code == 404
