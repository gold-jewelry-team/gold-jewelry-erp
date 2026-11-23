from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from uuid import UUID

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.purchase import Purchase
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill
from app.routers import purchases, supplier_payables


def test_purchase_can_be_cancelled_after_linked_bill_is_void():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-VOID-BILL", name="作廢帳單採購取消測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-VOID-BILL", order_date=date(2026, 11, 23),
        status="ORDERED", currency_code="TWD",
    )
    db.add(purchase)
    db.commit()
    company_id, site_id, supplier_id, purchase_id = company.id, site.id, supplier.id, purchase.id
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
    try:
        client = TestClient(app)
        bill = client.post(f"/companies/{company_id}/supplier-payables/bills", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "purchase_id": str(purchase_id), "bill_no": "INV-VOID-BILL",
            "bill_date": "2026-11-23", "currency_code": "TWD",
            "total_amount": "8000.00",
        })
        assert bill.status_code == 201, bill.text

        db = TestSession()
        stored_bill = db.get(SupplierBill, UUID(bill.json()["id"]))
        stored_bill.status = "VOID"
        db.commit()
        db.close()

        cancelled = client.post(f"/companies/{company_id}/purchases/{purchase_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "CANCELLED"

        refreshed = client.get(f"/companies/{company_id}/purchases/{purchase_id}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "CANCELLED"
        bill_after = client.get(
            f"/companies/{company_id}/supplier-payables/bills/{bill.json()['id']}"
        )
        assert bill_after.status_code == 200, bill_after.text
        assert bill_after.json()["status"] == "VOID"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
