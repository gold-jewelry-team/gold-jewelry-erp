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
from app.models.purchase import Purchase
from app.models.site import Site
from app.models.supplier import Supplier
from app.routers import purchases, supplier_payables


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-CANCEL-BILL", name="採購帳單取消保護測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-HAS-BILL", order_date=date(2026, 11, 23),
        status="ORDERED", currency_code="TWD",
    )
    db.add(purchase)
    db.commit()
    ids = company.id, site.id, supplier.id, purchase.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[purchases.get_db] = override_db
    app.dependency_overrides[supplier_payables.get_db] = override_db
    return engine, TestSession, ids


def test_purchase_cannot_be_cancelled_while_active_supplier_bill_is_linked():
    engine, TestSession, (company_id, site_id, supplier_id, purchase_id) = _context()
    try:
        client = TestClient(app)
        bill = client.post(f"/companies/{company_id}/supplier-payables/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_id": str(purchase_id),
            "bill_no": "INV-PO-CANCEL-BLOCK",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "12000.00",
        })
        assert bill.status_code == 201, bill.text

        rejected = client.post(f"/companies/{company_id}/purchases/{purchase_id}/cancel")
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["detail"] == "採購單已有有效供應商帳單，請先處理帳款後再取消。"

        purchase = client.get(f"/companies/{company_id}/purchases/{purchase_id}")
        assert purchase.status_code == 200, purchase.text
        assert purchase.json()["status"] == "ORDERED"

        refreshed_bill = client.get(
            f"/companies/{company_id}/supplier-payables/bills/{bill.json()['id']}"
        )
        assert refreshed_bill.status_code == 200, refreshed_bill.text
        assert refreshed_bill.json()["status"] == "OPEN"
        assert Decimal(refreshed_bill.json()["paid_amount"]) == Decimal("0.00")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
