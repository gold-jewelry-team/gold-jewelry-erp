from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, create_engine
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


def _stocktake_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="STK-ATOMIC", name="盤點整批原子性測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    location = StorageLocation(
        site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
    )
    first = Product(
        company_id=company.id, product_code="STK-G-001", name="盤點商品一",
        gross_weight=Decimal("1.2000"), net_weight=Decimal("1.1000"),
    )
    second = Product(
        company_id=company.id, product_code="STK-G-002", name="盤點商品二",
        gross_weight=Decimal("0.9000"), net_weight=Decimal("0.8000"),
    )
    db.add_all([location, first, second])
    db.commit()
    ids = (company.id, site.id, location.id, first.id, second.id)
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[inventory.get_db] = override_db
    return engine, TestSession, ids


def _opening_stock(client, company_id, site_id, location_id, product_id, quantity, weight):
    response = client.post(
        f"/companies/{company_id}/inventory/adjustments",
        json={
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "IN",
            "quantity": str(quantity),
            "weight": str(weight),
            "weight_unit_code": "QIAN",
            "note": "盤點測試期初庫存",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _item(product_id, location_id, expected, actual, weight, key=None):
    return {
        "product_id": str(product_id),
        "location_id": str(location_id),
        "expected_quantity": str(expected),
        "actual_quantity": str(actual),
        "expected_net_weight": str(weight),
        "idempotency_key": str(key or uuid4()),
    }


def test_stocktake_batch_applies_all_differences_and_exact_retry_is_safe():
    engine, TestSession, (company_id, site_id, location_id, first_id, second_id) = _stocktake_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/inventory"
        _opening_stock(client, company_id, site_id, location_id, first_id, "2", "1.1000")

        key_first, key_second = uuid4(), uuid4()
        payload = {
            "site_id": str(site_id),
            "items": [
                _item(first_id, location_id, "2", "1", "1.1000", key_first),
                _item(second_id, location_id, "0", "1", "0.8000", key_second),
            ],
        }

        first = client.post(f"{base}/stocktake-adjustments", json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["applied_count"] == 2
        assert first.json()["adjustment_count"] == 2
        assert first.json()["no_change_count"] == 0
        assert first.json()["replayed"] is False

        replay = client.post(f"{base}/stocktake-adjustments", json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        assert {
            row["id"] for row in replay.json()["movements"]
        } == {
            row["id"] for row in first.json()["movements"]
        }

        balances = client.get(
            f"{base}/stock",
            params={"site_id": str(site_id), "location_id": str(location_id)},
        )
        assert balances.status_code == 200, balances.text
        quantities = {row["product_id"]: row["quantity"] for row in balances.json()}
        assert quantities[str(first_id)] == "1.000"
        assert quantities[str(second_id)] == "1.000"

        changed_same_key = {
            **payload,
            "items": [
                _item(first_id, location_id, "2", "3", "1.1000", key_first),
                payload["items"][1],
            ],
        }
        conflict = client.post(f"{base}/stocktake-adjustments", json=changed_same_key)
        assert conflict.status_code == 409, conflict.text

        verify = TestSession()
        count = verify.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company_id
            )
        )
        assert count == 3  # One opening movement plus two stocktake adjustments.
        stocktake_count = verify.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.reference_type == "STOCKTAKE",
            )
        )
        assert stocktake_count == 2
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_stocktake_stale_snapshot_rejects_entire_batch_without_partial_writes():
    engine, TestSession, (company_id, site_id, location_id, first_id, second_id) = _stocktake_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/inventory"
        _opening_stock(client, company_id, site_id, location_id, first_id, "1", "1.1000")
        _opening_stock(client, company_id, site_id, location_id, second_id, "1", "0.8000")

        # Simulate a sale after the operator loaded the stocktake baseline.
        changed_by_sale = client.post(f"{base}/adjustments", json={
            "site_id": str(site_id),
            "product_id": str(second_id),
            "location_id": str(location_id),
            "direction": "OUT",
            "quantity": "1",
            "weight": "0.8000",
            "weight_unit_code": "QIAN",
            "note": "盤點期間完成銷售",
            "idempotency_key": str(uuid4()),
        })
        assert changed_by_sale.status_code == 201, changed_by_sale.text

        payload = {
            "site_id": str(site_id),
            "items": [
                _item(first_id, location_id, "1", "0", "1.1000"),
                _item(second_id, location_id, "1", "0", "0.8000"),
            ],
        }
        rejected = client.post(f"{base}/stocktake-adjustments", json=payload)
        assert rejected.status_code == 409, rejected.text
        assert "整批未入帳" in rejected.json()["detail"]

        balances = client.get(
            f"{base}/stock",
            params={"site_id": str(site_id), "location_id": str(location_id), "include_zero": "true"},
        )
        assert balances.status_code == 200, balances.text
        quantities = {row["product_id"]: row["quantity"] for row in balances.json()}
        assert quantities[str(first_id)] == "1.000"
        assert quantities[str(second_id)] == "0.000"

        verify = TestSession()
        stocktake_count = verify.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.reference_type == "STOCKTAKE",
            )
        )
        assert stocktake_count == 0
        total = verify.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company_id
            )
        )
        assert total == 3  # Two opening movements and the intervening sale only.
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_stocktake_snapshot_weight_change_rejects_batch():
    engine, TestSession, (company_id, site_id, location_id, first_id, second_id) = _stocktake_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/inventory"
        _opening_stock(client, company_id, site_id, location_id, first_id, "1", "1.1000")

        db = TestSession()
        product = db.get(Product, first_id)
        product.net_weight = Decimal("1.0500")
        db.commit()
        db.close()

        payload = {
            "site_id": str(site_id),
            "items": [_item(first_id, location_id, "1", "0", "1.1000")],
        }
        response = client.post(f"{base}/stocktake-adjustments", json=payload)
        assert response.status_code == 409, response.text
        assert "淨重已" in response.json()["detail"]

        verify = TestSession()
        balance = client.get(
            f"{base}/stock",
            params={"site_id": str(site_id), "location_id": str(location_id)},
        )
        assert balance.status_code == 200, balance.text
        assert balance.json()[0]["quantity"] == "1.000"
        count = verify.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.reference_type == "STOCKTAKE",
            )
        )
        assert count == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
