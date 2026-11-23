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
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import (
    SupplierBill,
    SupplierPayment,
    SupplierPaymentAllocation,
)
from app.routers import supplier_payables


def test_supplier_payables_api_isolates_bills_and_payments_by_company():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="PAYABLE-OWNER", name="應付帳款所屬公司")
    other = Company(code="PAYABLE-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    owner_site = Site(company_id=owner.id, code="MAIN", name="總店")
    other_site = Site(company_id=other.id, code="MAIN", name="總店")
    owner_supplier = Supplier(company_id=owner.id, code="SUP-01", name="甲供應商")
    other_supplier = Supplier(company_id=other.id, code="SUP-01", name="乙供應商")
    db.add_all([owner_site, other_site, owner_supplier, other_supplier])
    db.commit()
    owner_id, other_id = owner.id, other.id
    owner_site_id, other_site_id = owner_site.id, other_site.id
    owner_supplier_id, other_supplier_id = owner_supplier.id, other_supplier.id
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
        owner_base = f"/companies/{owner_id}/supplier-payables"
        other_base = f"/companies/{other_id}/supplier-payables"
        created = client.post(f"{owner_base}/bills", json={
            "site_id": str(owner_site_id),
            "supplier_id": str(owner_supplier_id),
            "bill_no": "INV-COMPANY-ISOLATION",
            "bill_date": date(2026, 11, 23).isoformat(),
            "currency_code": "TWD",
            "total_amount": "1200.00",
        })
        assert created.status_code == 201, created.text
        foreign_bill_id = created.json()["id"]

        listing = client.get(f"{other_base}/bills")
        assert listing.status_code == 200, listing.text
        assert listing.json() == []

        detail = client.get(f"{other_base}/bills/{foreign_bill_id}")
        assert detail.status_code == 404

        payment = client.post(f"{other_base}/payments", json={
            "site_id": str(other_site_id),
            "supplier_id": str(other_supplier_id),
            "payment_no": "SP-CROSS-COMPANY",
            "payment_method": "TRANSFER",
            "allocations": [{
                "bill_id": foreign_bill_id,
                "amount": "500.00",
            }],
        })
        assert payment.status_code == 422
        assert "相同公司、據點及供應商" in payment.json()["detail"]

        verify = TestSession()
        foreign_bill = verify.get(SupplierBill, UUID(foreign_bill_id))
        assert foreign_bill.status == "OPEN"
        assert foreign_bill.total_amount == 1200
        assert verify.query(SupplierPayment).count() == 0
        assert verify.query(SupplierPaymentAllocation).count() == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
