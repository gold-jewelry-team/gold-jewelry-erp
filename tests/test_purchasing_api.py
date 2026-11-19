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
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.product import Product
from app.routers import product_master, purchases, suppliers


def test_supplier_purchase_submit_and_receive_api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="API-STORE", name="API測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    second_location = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
    product = Product(company_id=company.id, product_code="API-G-001", name="測試金戒",
                      gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"))
    session.add_all([location, second_location, product])
    session.commit()
    company_id, site_id, location_id, second_location_id, product_id = company.id, site.id, location.id, second_location.id, product.id
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[suppliers.get_db] = override_db
    app.dependency_overrides[purchases.get_db] = override_db
    app.dependency_overrides[product_master.get_db] = override_db
    try:
        client = TestClient(app)
        supplier_response = client.post(f"/companies/{company_id}/suppliers",
                                        json={"code": "SUP-API", "name": "測試供應商"})
        assert supplier_response.status_code == 201, supplier_response.text
        supplier_id = supplier_response.json()["id"]

        purchase_response = client.post(f"/companies/{company_id}/purchases", json={
            "site_id": str(site_id), "supplier_id": supplier_id,
            "purchase_no": "PO-API-001", "order_date": date.today().isoformat(),
            "currency_code": "TWD",
            "lines": [{"product_id": str(product_id), "quantity": "2",
                       "weight": "1.1", "weight_unit_code": "QIAN", "unit_cost": "12000", "cost_labor_fee": "350"}],
        })
        assert purchase_response.status_code == 201, purchase_response.text
        purchase = purchase_response.json()
        assert purchase["status"] == "DRAFT"
        assert purchase["lines"][0]["cost_labor_fee"] == "350.00"

        listed = client.get(
            f"/companies/{company_id}/purchases",
            params={"site_id": str(site_id), "status": "DRAFT"},
        )
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == purchase["id"]
        purchase_id, line_id = purchase["id"], purchase["lines"][0]["id"]

        submitted = client.post(f"/companies/{company_id}/purchases/{purchase_id}/submit")
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "ORDERED"

        first_received = client.post(f"/companies/{company_id}/purchases/{purchase_id}/receive", json={
            "purchase_line_id": line_id, "location_id": str(location_id), "received_quantity": "1",
        })
        assert first_received.status_code == 200, first_received.text
        assert first_received.json()["status"] == "PARTIALLY_RECEIVED"

        second_received = client.post(f"/companies/{company_id}/purchases/{purchase_id}/receive", json={
            "purchase_line_id": line_id, "location_id": str(second_location_id), "received_quantity": "1",
        })
        assert second_received.status_code == 200, second_received.text
        assert second_received.json()["status"] == "RECEIVED"

        label_lots = client.get(f"/companies/{company_id}/products/{product_id}/label-lots")
        assert label_lots.status_code == 200, label_lots.text
        assert len(label_lots.json()) == 2
        lots = label_lots.json()
        assert {lot["location_code"] for lot in lots} == {"SAFE", "SHOW"}
        for lot in lots:
            assert lot["purchase_no"] == "PO-API-001"
            assert lot["supplier_code"] == "SUP-API"
            assert lot["supplier_name"] == "測試供應商"
            assert lot["received_quantity"] == "1.000"
            assert lot["cost_labor_fee"] == "350.00"
            assert lot["currency_code"] == "TWD"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
