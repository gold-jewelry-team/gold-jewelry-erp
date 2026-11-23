from datetime import date
from uuid import UUID

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
from app.routers import purchases, supplier_payables


def test_purchase_cancellation_is_blocked_when_any_linked_bill_remains_active():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-MIXED-BILLS", name="多張帳單取消保護測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-MIXED-BILL-STATUS", order_date=date(2026, 11, 23),
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
        bill_ids = []
        for bill_no in ("INV-MIXED-VOID", "INV-MIXED-OPEN"):
            response = client.post(
                f"/companies/{company_id}/supplier-payables/bills",
                json={
                    "site_id": str(site_id), "supplier_id": str(supplier_id),
                    "purchase_id": str(purchase_id), "bill_no": bill_no,
                    "bill_date": "2026-11-23", "currency_code": "TWD",
                    "total_amount": "3000.00",
                },
            )
            assert response.status_code == 201, response.text
            bill_ids.append(response.json()["id"])

        db = TestSession()
        void_bill = db.get(SupplierBill, UUID(bill_ids[0]))
        void_bill.status = "VOID"
        db.commit()
        db.close()

        rejected = client.post(f"/companies/{company_id}/purchases/{purchase_id}/cancel")
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["detail"] == "採購單已有有效供應商帳單，請先處理帳款後再取消。"

        purchase_after = client.get(f"/companies/{company_id}/purchases/{purchase_id}")
        assert purchase_after.status_code == 200, purchase_after.text
        assert purchase_after.json()["status"] == "ORDERED"
        void_after = client.get(
            f"/companies/{company_id}/supplier-payables/bills/{bill_ids[0]}"
        )
        open_after = client.get(
            f"/companies/{company_id}/supplier-payables/bills/{bill_ids[1]}"
        )
        assert void_after.json()["status"] == "VOID"
        assert open_after.json()["status"] == "OPEN"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
