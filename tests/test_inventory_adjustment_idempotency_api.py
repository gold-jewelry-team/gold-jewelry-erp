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


def test_replaying_same_manual_adjustment_returns_original_movement_once():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="IDEMPOTENT-STOCK", name="盤點重送測試銀樓")
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
        product_code="IDEMPOTENT-001",
        name="冪等盤點測試商品",
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
        url = f"/companies/{company_id}/inventory/adjustments"
        key = str(uuid4())
        missing_key = client.post(url, json={
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "IN",
            "quantity": "2",
        })
        assert missing_key.status_code == 422, missing_key.text
        verify_empty = TestSession()
        assert verify_empty.query(InventoryMovement).count() == 0
        verify_empty.close()

        received = client.post(url, json={
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "IN",
            "quantity": "2",
            "idempotency_key": str(uuid4()),
        })
        assert received.status_code == 201, received.text

        payload = {
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "OUT",
            "quantity": "2",
            "weight": "1.0000",
            "weight_unit_code": "QIAN",
            "note": "盤點差異重送測試",
            "idempotency_key": key,
        }

        first = client.post(url, json=payload)
        replay = client.post(url, json=payload)

        assert first.status_code == 201, first.text
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]

        verify = TestSession()
        rows = verify.query(InventoryMovement).all()
        assert len(rows) == 2
        manual_rows = [row for row in rows if row.reference_type == "MANUAL_ADJUSTMENT"]
        assert len(manual_rows) == 2  # One opening adjustment plus the keyed adjustment.
        keyed_rows = [
            row for row in manual_rows
            if row.reference_id.hex == key.replace("-", "")
        ]
        assert len(keyed_rows) == 1
        assert keyed_rows[0].movement_type == "ADJUSTMENT"
        verify.close()

        stock = client.get(
            f"/companies/{company_id}/inventory/stock",
            params={"site_id": str(site_id), "location_id": str(location_id), "include_zero": "true"},
        )
        assert stock.status_code == 200, stock.text
        assert stock.json()[0]["quantity"] == "0.000"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_reusing_manual_adjustment_key_for_different_content_is_rejected():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="IDEMPOTENT-CONFLICT", name="盤點重送衝突測試")
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
        product_code="IDEMPOTENT-CONFLICT-001",
        name="冪等衝突測試商品",
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
        url = f"/companies/{company_id}/inventory/adjustments"
        key = str(uuid4())
        common = {
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "IN",
            "weight_unit_code": "QIAN",
            "idempotency_key": key,
            "occurred_at": "2026-01-01T08:00:00+08:00",
        }
        first = client.post(url, json={**common, "quantity": "2"})
        equivalent_timestamp_replay = client.post(url, json={
            **common,
            "quantity": "2",
            "occurred_at": "2026-01-01T00:00:00Z",
        })
        conflict = client.post(url, json={**common, "quantity": "3"})
        timestamp_conflict = client.post(url, json={
            **common,
            "quantity": "2",
            "occurred_at": "2026-01-02T00:00:00Z",
        })

        assert first.status_code == 201, first.text
        assert equivalent_timestamp_replay.status_code == 200, equivalent_timestamp_replay.text
        assert equivalent_timestamp_replay.json()["id"] == first.json()["id"]
        assert conflict.status_code == 409, conflict.text
        assert timestamp_conflict.status_code == 409, timestamp_conflict.text
        assert "冪等識別碼" in conflict.json()["detail"]

        verify = TestSession()
        rows = verify.query(InventoryMovement).all()
        assert len(rows) == 1
        verify.close()

        stock = client.get(
            f"/companies/{company_id}/inventory/stock",
            params={"site_id": str(site_id), "location_id": str(location_id)},
        )
        assert stock.status_code == 200, stock.text
        assert stock.json()[0]["quantity"] == "2.000"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
