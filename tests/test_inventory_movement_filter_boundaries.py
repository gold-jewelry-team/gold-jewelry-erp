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


def test_movement_history_filters_type_and_inclusive_time_bounds():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="MOVE-FILTER", name="異動篩選測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code="MOVE-FILTER-001", name="異動測試商品")
    db.add_all([location, product])
    db.flush()
    start = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    middle = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc)
    create_inventory_movement(db, company_id=company.id, site_id=site.id, product_id=product.id,
        movement_type="RECEIPT", quantity=Decimal("3"), to_location_id=location.id, occurred_at=start)
    create_inventory_movement(db, company_id=company.id, site_id=site.id, product_id=product.id,
        movement_type="ADJUSTMENT", quantity=Decimal("1"), to_location_id=location.id, occurred_at=middle)
    create_inventory_movement(db, company_id=company.id, site_id=site.id, product_id=product.id,
        movement_type="RECEIPT", quantity=Decimal("2"), to_location_id=location.id, occurred_at=end)
    db.commit()
    company_id, product_id = company.id, product.id
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
        base = f"/companies/{company_id}/inventory/movements"
        selected = client.get(base, params={
            "product_id": str(product_id), "movement_type": "RECEIPT",
            "since": start.isoformat(), "until": end.isoformat(),
        })
        assert selected.status_code == 200, selected.text
        assert len(selected.json()) == 2
        assert [row["quantity"] for row in selected.json()] == ["2.000", "3.000"]
        excluded_type = client.get(base, params={
            "product_id": str(product_id), "movement_type": "SALE",
            "since": start.isoformat(), "until": end.isoformat(),
        })
        assert excluded_type.status_code == 200
        assert excluded_type.json() == []
        invalid_type = client.get(base, params={"movement_type": "UNKNOWN"})
        assert invalid_type.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
