from datetime import datetime, timezone
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
from app.routers import inventory
from app.services.inventory import create_inventory_movement


def test_stock_api_as_of_returns_balances_before_and_after_transfer():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="STOCK-ASOF", name="歷史庫存 API 測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
    product = Product(company_id=company.id, product_code="STOCK-ASOF-001", name="歷史庫存戒指")
    db.add_all([safe, show, product])
    db.flush()
    received = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    moved = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    create_inventory_movement(db, company_id=company.id, site_id=site.id, product_id=product.id,
        movement_type="RECEIPT", quantity=Decimal("5"), to_location_id=safe.id, occurred_at=received)
    create_inventory_movement(db, company_id=company.id, site_id=site.id, product_id=product.id,
        movement_type="TRANSFER", quantity=Decimal("2"), from_location_id=safe.id, to_location_id=show.id,
        occurred_at=moved)
    db.commit()
    company_id, safe_id, show_id = company.id, safe.id, show.id
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
        base = f"/companies/{company_id}/inventory/stock"
        before = client.get(base, params={"as_of": "2026-11-21T09:59:00+00:00"})
        assert before.status_code == 200, before.text
        assert {r["location_id"]: r["quantity"] for r in before.json()} == {str(safe_id): "5.000"}
        after = client.get(base, params={"as_of": "2026-11-21T10:01:00+00:00"})
        assert after.status_code == 200, after.text
        assert {r["location_id"]: r["quantity"] for r in after.json()} == {
            str(safe_id): "3.000", str(show_id): "2.000"
        }
        assert sum(Decimal(r["quantity"]) for r in after.json()) == Decimal("5.000")
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
