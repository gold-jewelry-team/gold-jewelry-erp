from decimal import Decimal
from uuid import uuid4

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
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import inventory


def test_outgoing_stock_adjustment_cannot_overdraw_inventory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ADJ-OVERDRAW", name="庫存調整不可超扣測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id,
        product_code="ADJ-OVERDRAW-001",
        name="庫存調整測試戒指",
        gross_weight=Decimal("1.0000"),
        net_weight=Decimal("1.0000"),
    )
    db.add_all([location, product])
    db.commit()
    company_id, site_id, location_id, product_id = (
        company.id, site.id, location.id, product.id
    )
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[inventory.get_db] = override_db
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/inventory"
        received = client.post(f"{base}/adjustments", json={
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "IN",
            "quantity": "2",
            "idempotency_key": str(uuid4()),
        })
        assert received.status_code == 201, received.text

        overdraw = client.post(f"{base}/adjustments", json={
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "OUT",
            "quantity": "2.001",
            "idempotency_key": str(uuid4()),
        })
        assert overdraw.status_code == 422
        assert "庫存不足" in overdraw.json()["detail"]

        stock = client.get(
            f"{base}/stock",
            params={"site_id": str(site_id), "location_id": str(location_id)},
        )
        assert stock.status_code == 200, stock.text
        assert len(stock.json()) == 1
        assert stock.json()[0]["quantity"] == "2.000"

        verify = TestSession()
        movements = verify.query(InventoryMovement).all()
        assert len(movements) == 1
        assert movements[0].movement_type == "ADJUSTMENT"
        assert movements[0].quantity == Decimal("2.000")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
