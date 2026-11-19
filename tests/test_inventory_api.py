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
from app.routers import inventory


def test_inventory_adjustment_transfer_balance_and_negative_stock_guard():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="INV-API", name="庫存 API 測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    a = StorageLocation(site_id=site.id, code="A", name="展示櫃", location_type="STORE_FLOOR")
    b = StorageLocation(site_id=site.id, code="B", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code="INV-G-001", name="測試金戒",
                      gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"))
    db.add_all([a, b, product])
    db.commit()
    company_id, site_id, a_id, b_id, product_id = company.id, site.id, a.id, b.id, product.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[inventory.get_db] = override_db
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/inventory"
        incoming = client.post(f"{base}/adjustments", json={
            "site_id": str(site_id), "product_id": str(product_id),
            "location_id": str(a_id), "direction": "IN", "quantity": "2",
        })
        assert incoming.status_code == 201, incoming.text

        transfer = client.post(f"{base}/transfers", json={
            "site_id": str(site_id), "product_id": str(product_id),
            "from_location_id": str(a_id), "to_location_id": str(b_id), "quantity": "1",
        })
        assert transfer.status_code == 201, transfer.text

        balances = client.get(f"{base}/stock")
        assert balances.status_code == 200, balances.text
        by_location = {row["location_id"]: row["quantity"] for row in balances.json()}
        assert by_location[str(a_id)] == "1.000"
        assert by_location[str(b_id)] == "1.000"

        insufficient = client.post(f"{base}/transfers", json={
            "site_id": str(site_id), "product_id": str(product_id),
            "from_location_id": str(a_id), "to_location_id": str(b_id), "quantity": "2",
        })
        assert insufficient.status_code == 422
        history = client.get(f"{base}/movements", params={"product_id": str(product_id)})
        assert history.status_code == 200
        assert len(history.json()) == 2
    finally:
        app.dependency_overrides.pop(inventory.get_db, None)
        engine.dispose()
