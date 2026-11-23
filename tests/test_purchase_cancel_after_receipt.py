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
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.routers import inventory, purchases, suppliers


def test_partially_received_purchase_cannot_be_cancelled_and_receipt_remains():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-PARTIAL-CANCEL", name="部分驗收採購取消測試")
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
        company_id=company.id, product_code="PO-CANCEL-001", name="測試黃金戒指",
        gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"),
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
    app.dependency_overrides[suppliers.get_db] = override_db
    app.dependency_overrides[inventory.get_db] = override_db
    try:
        client = TestClient(app)
        created_supplier = client.get(f"/companies/{company_id}/suppliers")
        assert created_supplier.status_code == 200, created_supplier.text

        created = client.post(f"/companies/{company_id}/purchases", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "purchase_no": "PO-PARTIAL-CANCEL-001",
            "order_date": date(2026, 11, 23).isoformat(), "currency_code": "TWD",
            "lines": [{
                "product_id": str(product_id), "quantity": "2",
                "weight": "2.0000", "weight_unit_code": "QIAN",
                "unit_cost": "12000.00", "cost_labor_fee": "300.00",
            }],
        })
        assert created.status_code == 201, created.text
        purchase_id = created.json()["id"]
        line_id = created.json()["lines"][0]["id"]

        submitted = client.post(f"/companies/{company_id}/purchases/{purchase_id}/submit")
        assert submitted.status_code == 200, submitted.text
        received = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/receive",
            json={
                "purchase_line_id": line_id, "location_id": str(location_id),
                "received_quantity": "1",
            },
        )
        assert received.status_code == 200, received.text
        assert received.json()["status"] == "PARTIALLY_RECEIVED"

        rejected = client.post(f"/companies/{company_id}/purchases/{purchase_id}/cancel")
        assert rejected.status_code == 422, rejected.text
        assert "只有草稿或尚未收貨的採購單可以取消" in rejected.json()["detail"]

        refreshed = client.get(f"/companies/{company_id}/purchases/{purchase_id}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "PARTIALLY_RECEIVED"
        assert refreshed.json()["lines"][0]["received_quantity"] == "1.000"

        stock = client.get(
            f"/companies/{company_id}/inventory/stock",
            params={"site_id": str(site_id)},
        )
        assert stock.status_code == 200, stock.text
        assert sum(
            (Decimal(item["quantity"]) for item in stock.json()
             if item["product_id"] == str(product_id)),
            Decimal("0"),
        ) == Decimal("1.000")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
