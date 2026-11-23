from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.routers import purchases


def test_cancelled_purchase_cannot_be_received_or_create_inventory_movement():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-CANCEL-RECEIVE", name="已取消採購驗收保護測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id, product_code="PO-CANCEL-RECEIVE-001",
        name="測試黃金項鍊", gross_weight=Decimal("2.0"), net_weight=Decimal("1.9"),
    )
    db.add_all([supplier, location, product])
    db.commit()
    company_id, site_id, supplier_id = company.id, site.id, supplier.id
    location_id, product_id = location.id, product.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[purchases.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/purchases", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "purchase_no": "PO-CANCEL-THEN-RECEIVE",
            "order_date": date(2026, 11, 23).isoformat(), "currency_code": "TWD",
            "lines": [{
                "product_id": str(product_id), "quantity": "2",
                "weight": "2.0000", "weight_unit_code": "QIAN",
                "unit_cost": "12000.00", "cost_labor_fee": "250.00",
            }],
        })
        assert created.status_code == 201, created.text
        purchase_id = created.json()["id"]
        line_id = created.json()["lines"][0]["id"]

        submitted = client.post(f"/companies/{company_id}/purchases/{purchase_id}/submit")
        assert submitted.status_code == 200, submitted.text
        cancelled = client.post(f"/companies/{company_id}/purchases/{purchase_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "CANCELLED"

        rejected = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/receive",
            json={
                "purchase_line_id": line_id, "location_id": str(location_id),
                "received_quantity": "1",
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert "只有已下單或部分到貨的採購單可以驗收" in rejected.json()["detail"]

        check = TestSession()
        purchase = check.get(Purchase, UUID(purchase_id))
        line = check.get(PurchaseLine, UUID(line_id))
        assert purchase.status == "CANCELLED"
        assert line.received_quantity == Decimal("0")
        assert check.query(InventoryMovement).filter_by(
            reference_type="PURCHASE_LINE", reference_id=line.id
        ).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
