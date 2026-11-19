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
from app.routers import purchases, suppliers


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
    product = Product(company_id=company.id, product_code="API-G-001", name="測試金戒",
                      gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"))
    session.add_all([location, product])
    session.commit()
    company_id, site_id, location_id, product_id = company.id, site.id, location.id, product.id
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

        received = client.post(f"/companies/{company_id}/purchases/{purchase_id}/receive", json={
            "purchase_line_id": line_id, "location_id": str(location_id), "received_quantity": "2",
        })
        assert received.status_code == 200, received.text
        assert received.json()["status"] == "RECEIVED"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
