"""PostgreSQL concurrency coverage for explicit inventory-operation recovery."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app import models  # noqa: F401
from app.main import app
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.inventory_operation_request import InventoryOperationRequest
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import inventory
from app.routers.schemas.inventory import InventoryTransferCreate
from app.services.inventory_operation_requests import fingerprint_inventory_operation


DATABASE_URL = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="This integration test requires the PostgreSQL CI database.",
)


def test_concurrent_explicit_recovery_completes_one_stored_transfer():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    company_id = site_id = source_id = destination_id = product_id = request_id = None
    app.dependency_overrides.clear()

    try:
        with TestSession() as db:
            company = Company(
                code=f"RECOVERY-RACE-{uuid.uuid4().hex[:10]}",
                name="庫存恢復併發測試",
            )
            db.add(company)
            db.flush()
            site = Site(company_id=company.id, code="MAIN", name="總店")
            db.add(site)
            db.flush()
            source = StorageLocation(
                site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
            )
            destination = StorageLocation(
                site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
            )
            product = Product(
                company_id=company.id,
                product_code=f"RECOVERY-{uuid.uuid4().hex[:12]}",
                name="恢復併發測試商品",
                gross_weight=Decimal("1.0000"),
                net_weight=Decimal("1.0000"),
                weight_unit_code="QIAN",
            )
            db.add_all([source, destination, product])
            db.flush()

            company_id, site_id = company.id, site.id
            source_id, destination_id, product_id = source.id, destination.id, product.id
            db.add(InventoryMovement(
                company_id=company_id,
                site_id=site_id,
                product_id=product_id,
                movement_type="RECEIPT",
                to_location_id=source_id,
                quantity=Decimal("5.000"),
                weight=Decimal("1.0000"),
                weight_unit_code="QIAN",
                reference_type="TEST_FIXTURE",
                note="恢復併發測試期初庫存",
            ))

            key = uuid.uuid4()
            raw_payload = {
                "site_id": str(site_id),
                "product_id": str(product_id),
                "from_location_id": str(source_id),
                "to_location_id": str(destination_id),
                "quantity": "2.000",
                "weight": "1.0000",
                "weight_unit_code": "QIAN",
                "note": "同一筆原始調撥",
                "idempotency_key": str(key),
            }
            validated = InventoryTransferCreate.model_validate(raw_payload)
            canonical, fingerprint = fingerprint_inventory_operation(
                operation_type="MANUAL_TRANSFER",
                company_id=company_id,
                site_id=site_id,
                payload=validated.model_dump(mode="python"),
            )
            request = InventoryOperationRequest(
                company_id=company_id,
                site_id=site_id,
                idempotency_key=key,
                operation_type="MANUAL_TRANSFER",
                payload=canonical,
                payload_fingerprint=fingerprint,
                status="PENDING",
            )
            db.add(request)
            db.commit()
            request_id = request.id

        def override_db():
            session = TestSession()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[inventory.get_db] = override_db
        barrier = threading.Barrier(2)

        def retry_same_request():
            barrier.wait(timeout=10)
            with TestClient(app) as client:
                return client.post(
                    f"/companies/{company_id}/inventory/operation-requests/{request_id}/retry"
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: retry_same_request(), range(2)))

        assert [response.status_code for response in responses] == [200, 200], [
            (response.status_code, response.text) for response in responses
        ]
        movement_ids = {response.json()["id"] for response in responses}
        assert len(movement_ids) == 1

        with TestSession() as verify:
            row = verify.get(InventoryOperationRequest, request_id)
            assert row.status == "COMPLETED"
            assert row.movement_id == uuid.UUID(next(iter(movement_ids)))
            count = verify.scalar(
                select(func.count()).select_from(InventoryMovement).where(
                    InventoryMovement.company_id == company_id,
                    InventoryMovement.movement_type == "TRANSFER",
                    InventoryMovement.reference_id == key,
                )
            )
            assert count == 1
    finally:
        app.dependency_overrides.clear()
        if company_id is not None:
            with TestSession() as cleanup:
                cleanup.execute(delete(InventoryOperationRequest).where(
                    InventoryOperationRequest.company_id == company_id
                ))
                cleanup.execute(delete(InventoryMovement).where(
                    InventoryMovement.company_id == company_id
                ))
                cleanup.execute(delete(Product).where(Product.company_id == company_id))
                if source_id is not None:
                    cleanup.execute(delete(StorageLocation).where(
                        StorageLocation.id.in_([source_id, destination_id])
                    ))
                if site_id is not None:
                    cleanup.execute(delete(Site).where(Site.id == site_id))
                cleanup.execute(delete(Company).where(Company.id == company_id))
                cleanup.commit()
        engine.dispose()
