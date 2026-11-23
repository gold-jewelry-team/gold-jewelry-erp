from datetime import date

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
from app.models.supplier_payable import SupplierBill
from app.routers import supplier_payables


def test_supplier_bill_api_rejects_link_to_cancelled_purchase_without_records():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BILL-CANCELLED-PO-API", name="取消採購應付帳單 API 測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    purchase = Purchase(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        purchase_no="PO-CANCELLED-BILL-API",
        order_date=date(2026, 11, 23),
        currency_code="TWD",
        status="CANCELLED",
    )
    db.add(purchase)
    db.commit()
    company_id, site_id = company.id, site.id
    supplier_id, purchase_id = supplier.id, purchase.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[supplier_payables.get_db] = override_db
    try:
        client = TestClient(app)
        rejected = client.post(
            f"/companies/{company_id}/supplier-payables/bills",
            json={
                "site_id": str(site_id),
                "supplier_id": str(supplier_id),
                "purchase_id": str(purchase_id),
                "bill_no": "INV-CANCELLED-PO-API",
                "bill_date": "2026-11-23",
                "currency_code": "TWD",
                "total_amount": "5000.00",
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert "採購單狀態不允許建立應付帳單" in rejected.json()["detail"]

        verify = TestSession()
        assert verify.query(SupplierBill).count() == 0
        persisted_purchase = verify.get(Purchase, purchase_id)
        assert persisted_purchase.status == "CANCELLED"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
