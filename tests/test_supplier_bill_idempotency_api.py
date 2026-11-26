from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill
from app.routers import supplier_payables


def _bill_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with TestSession() as db:
        company = Company(code="BILL-RETRY", name="供應商帳單重送測試")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(
            company_id=company.id, code="SUP-RETRY", name="重送測試供應商"
        )
        db.add_all([site, supplier])
        db.commit()
        ids = (company.id, site.id, supplier.id)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[supplier_payables.get_db] = override_db
    return engine, TestSession, ids


def test_exact_supplier_bill_create_retry_returns_original_bill_without_duplicate():
    engine, TestSession, (company_id, site_id, supplier_id) = _bill_context()
    try:
        client = TestClient(app)
        url = f"/companies/{company_id}/supplier-payables/bills"
        payload = {
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-RETRY-001",
            "bill_date": "2026-11-26",
            "due_date": "2026-12-26",
            "currency_code": "twd",
            "total_amount": "1280.00",
            "note": "供應商月結帳單",
        }

        first = client.post(url, json=payload)
        replay = client.post(url, json={**payload, "currency_code": "TWD"})

        assert first.status_code == 201, first.text
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["bill_no"] == "INV-RETRY-001"
        assert replay.json()["currency_code"] == "TWD"
        assert replay.json()["total_amount"] == "1280.00"

        with TestSession() as db:
            rows = list(db.scalars(select(SupplierBill)).all())
            assert len(rows) == 1
            assert rows[0].id == UUID(first.json()["id"])
            assert rows[0].total_amount == Decimal("1280.00")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_bill_number_reuse_with_changed_content_is_rejected_atomically():
    engine, TestSession, (company_id, site_id, supplier_id) = _bill_context()
    try:
        client = TestClient(app)
        url = f"/companies/{company_id}/supplier-payables/bills"
        payload = {
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-RETRY-CONFLICT",
            "bill_date": "2026-11-26",
            "currency_code": "TWD",
            "total_amount": "900.00",
            "note": "原始帳單",
        }

        first = client.post(url, json=payload)
        conflict = client.post(
            url, json={**payload, "total_amount": "990.00"}
        )

        assert first.status_code == 201, first.text
        assert conflict.status_code == 409, conflict.text
        assert "不同內容" in conflict.json()["detail"]

        refreshed = client.get(
            f"/companies/{company_id}/supplier-payables/bills/{first.json()['id']}"
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["total_amount"] == "900.00"
        assert refreshed.json()["status"] == "OPEN"

        with TestSession() as db:
            rows = list(db.scalars(select(SupplierBill)).all())
            assert len(rows) == 1
            assert rows[0].total_amount == Decimal("900.00")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
