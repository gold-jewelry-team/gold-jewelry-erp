from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.operating_expense import OperatingExpense
from app.models.site import Site
from app.routers import cash_counts, daily_closing, expenses


def test_cash_operating_expense_reduces_expected_drawer_balance_at_daily_close():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="CASH-EXPENSE-E2E", name="現金費用盤點整合測試")
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
    app.dependency_overrides[expenses.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[cash_counts.get_db] = override_db
    try:
        client = TestClient(app)
        expense = client.post(
            f"/companies/{company_id}/operating-expenses",
            json={
                "site_id": str(site_id),
                "expense_no": "EXP-CASH-COUNT-001",
                "expense_date": datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat(),
                "category_code": "UTILITIES",
                "description": "以現金支付的水電費",
                "amount": "1200.00",
                "payment_method": "CASH",
            },
        )
        assert expense.status_code == 201, expense.text
        assert expense.json()["status"] == "PAID"
        assert expense.json()["payment_method"] == "CASH"

        business_date = datetime.now(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        snapshot = closing.json()
        assert snapshot["expenses_paid_amount"] == "1200.00"
        assert snapshot["net_cash_flow"] == "-1200.00"
        summaries = {
            row["payment_method"]: row for row in snapshot["payment_summaries"]
        }
        assert summaries["CASH"]["expenses_paid_amount"] == "1200.00"

        count = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings/"
            f"{snapshot['id']}/cash-count",
            json={
                "opening_cash_float": "2000.00",
                "counted_cash_amount": "800.00",
                "counted_by_name": "盤點甲",
            },
        )
        assert count.status_code == 201, count.text
        assert count.json()["expected_cash_amount"] == "800.00"
        assert count.json()["cash_variance"] == "0.00"

        verify = TestSession()
        persisted = verify.query(OperatingExpense).one()
        assert persisted.status == "PAID"
        assert persisted.paid_at is not None
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
