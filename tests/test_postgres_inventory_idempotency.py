"""PostgreSQL integration coverage for concurrent inventory retries."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import inventory


DATABASE_URL = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="This integration test requires the PostgreSQL CI database.",
)


def test_concurrent_same_inventory_adjustment_key_creates_one_movement():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    company_id = site_id = location_id = product_id = None
    app.dependency_overrides.clear()

    try:
        db = TestSession()
        company = Company(
            code=f"IDEMPOTENCY-RACE-{uuid.uuid4().hex[:10]}",
            name="庫存併發重送測試",
        )
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
            product_code=f"RACE-{uuid.uuid4().hex[:12]}",
            name="併發重送測試商品",
            gross_weight=Decimal("1.0000"),
            net_weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
        )
        db.add_all([location, product])
        db.flush()
        company_id, site_id, location_id, product_id = (
            company.id, site.id, location.id, product.id
        )
        db.add(InventoryMovement(
            company_id=company_id,
            site_id=site_id,
            product_id=product_id,
            movement_type="RECEIPT",
            to_location_id=location_id,
            quantity=Decimal("5.000"),
            weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
            reference_type="TEST_FIXTURE",
            note="併發測試期初庫存",
        ))
        db.commit()
        db.close()

        def override_db():
            session = TestSession()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[inventory.get_db] = override_db
        key = str(uuid.uuid4())
        payload = {
            "site_id": str(site_id),
            "product_id": str(product_id),
            "location_id": str(location_id),
            "direction": "OUT",
            "quantity": "2",
            "weight": "1.0000",
            "weight_unit_code": "QIAN",
            "note": "併發重送測試",
            "idempotency_key": key,
            "occurred_at": "2026-01-01T00:00:00Z",
        }
        barrier = threading.Barrier(2)

        def submit_same_request():
            barrier.wait(timeout=10)
            with TestClient(app) as client:
                return client.post(
                    f"/companies/{company_id}/inventory/adjustments",
                    json=payload,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: submit_same_request(), range(2)))

        assert sorted(response.status_code for response in responses) == [200, 201], [
            (response.status_code, response.text) for response in responses
        ]
        movement_ids = {response.json()["id"] for response in responses}
        assert len(movement_ids) == 1

        verify = TestSession()
        keyed_count = verify.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.reference_type == "MANUAL_ADJUSTMENT",
                InventoryMovement.reference_id == uuid.UUID(key),
            )
        )
        assert keyed_count == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        if company_id is not None:
            cleanup = TestSession()
            cleanup.execute(delete(InventoryMovement).where(InventoryMovement.company_id == company_id))
            cleanup.execute(delete(Product).where(Product.company_id == company_id))
            if location_id is not None:
                cleanup.execute(delete(StorageLocation).where(StorageLocation.id == location_id))
            if site_id is not None:
                cleanup.execute(delete(Site).where(Site.id == site_id))
            cleanup.execute(delete(Company).where(Company.id == company_id))
            cleanup.commit()
            cleanup.close()
        engine.dispose()
