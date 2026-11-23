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


def test_expense_api_rejects_foreign_site_and_duplicate_number_without_partial_writes():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="EXP-SCOPE-OWNER", name="費用所屬公司")
    other = Company(code="EXP-SCOPE-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    owner_site = Site(company_id=owner.id, code="MAIN", name="總店")
    other_site = Site(company_id=other.id, code="MAIN", name="其他公司總店")
    db.add_all([owner_site, other_site])
    db.commit()
    owner_id, owner_site_id, other_site_id = owner.id, owner_site.id, other_site.id
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
        base = f"/companies/{owner_id}/operating-expenses"
        payload = {
            "site_id": str(other_site_id),
            "expense_no": "EXP-SCOPE-001",
            "expense_date": "2026-11-23",
            "category_code": "UTILITIES",
            "description": "跨公司費用",
            "amount": "1200.00",
        }
        foreign = client.post(base, json=payload)
        assert foreign.status_code == 422
        assert "不屬於指定公司" in foreign.json()["detail"]

        payload["site_id"] = str(owner_site_id)
        first = client.post(base, json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["status"] == "UNPAID"

        duplicate = client.post(base, json=payload)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == first.json()["id"]

        conflicting = client.post(base, json={**payload, "amount": "1300.00"})
        assert conflicting.status_code == 409, conflicting.text
        assert "不同的費用內容" in conflicting.json()["detail"]

        verify = TestSession()
        rows = verify.query(OperatingExpense).all()
        assert len(rows) == 1
        assert rows[0].expense_no == "EXP-SCOPE-001"
        assert rows[0].amount == 1200
        assert rows[0].status == "UNPAID"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
