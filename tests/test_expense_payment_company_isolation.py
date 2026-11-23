from datetime import date
from decimal import Decimal

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
from app.routers import expenses


def test_other_company_cannot_pay_or_change_foreign_operating_expense():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="EXP-PAY-OWNER", name="費用所屬公司")
    other = Company(code="EXP-PAY-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    owner_site = Site(company_id=owner.id, code="MAIN", name="總店")
    other_site = Site(company_id=other.id, code="MAIN", name="其他公司總店")
    db.add_all([owner_site, other_site])
    db.flush()
    expense = OperatingExpense(
        company_id=owner.id,
        site_id=owner_site.id,
        expense_no="EXP-PAY-ISOLATION-001",
        expense_date=date(2026, 11, 23),
        category_code="UTILITIES",
        description="待付款水電費",
        amount=Decimal("980.00"),
        currency_code="TWD",
        status="UNPAID",
    )
    db.add(expense)
    db.commit()
    owner_id, other_id = owner.id, other.id
    owner_expense_id = expense.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[expenses.get_db] = override_db
    try:
        client = TestClient(app)
        rejected = client.post(
            f"/companies/{other_id}/operating-expenses/{owner_expense_id}/pay",
            json={"payment_method": "CASH"},
        )
        assert rejected.status_code == 422
        assert "找不到指定營業費用" in rejected.json()["detail"]

        owner_list = client.get(
            f"/companies/{owner_id}/operating-expenses",
            params={"status": "UNPAID"},
        )
        assert owner_list.status_code == 200, owner_list.text
        assert len(owner_list.json()) == 1
        assert owner_list.json()[0]["id"] == str(owner_expense_id)
        assert owner_list.json()[0]["status"] == "UNPAID"
        assert owner_list.json()[0]["paid_at"] is None

        verify = TestSession()
        persisted = verify.get(OperatingExpense, owner_expense_id)
        assert persisted.status == "UNPAID"
        assert persisted.payment_method is None
        assert persisted.paid_at is None
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
