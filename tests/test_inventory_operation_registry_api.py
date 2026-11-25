from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.inventory_operation_request import InventoryOperationRequest
from app.routers.schemas.inventory import InventoryTransferCreate
from app.services.inventory_operation_requests import fingerprint_inventory_operation
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import inventory


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as session:
        company = Company(code=f"OPREQ-{uuid4().hex[:8]}", name="操作恢復測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        source = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        destination = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        product = Product(
            company_id=company.id, product_code=f"OPREQ-{uuid4().hex[:8]}",
            name="操作恢復測試金戒", gross_weight=Decimal("1.2000"),
            net_weight=Decimal("1.0000"), weight_unit_code="QIAN",
        )
        session.add_all([source, destination, product])
        session.flush()
        session.add(InventoryMovement(
            company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", to_location_id=source.id,
            quantity=Decimal("5.000"), weight=Decimal("1.0000"),
            weight_unit_code="QIAN", reference_type="TEST_RECEIPT",
        ))
        ids = {
            "company_id": company.id, "site_id": site.id,
            "source_id": source.id, "destination_id": destination.id,
            "product_id": product.id,
        }
        session.commit()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[inventory.get_db] = override_db
    return engine, TestSession, ids


def _transfer_payload(ids, key):
    return {
        "site_id": str(ids["site_id"]),
        "product_id": str(ids["product_id"]),
        "from_location_id": str(ids["source_id"]),
        "to_location_id": str(ids["destination_id"]),
        "quantity": "2.000",
        "weight": "1.0000",
        "weight_unit_code": "QIAN",
        "note": "操作恢復登記測試",
        "idempotency_key": str(key),
    }


def test_transfer_request_is_durable_and_exact_retry_returns_original_movement():
    engine, TestSession, ids = _context()
    try:
        client = TestClient(app)
        url = f"/companies/{ids['company_id']}/inventory/transfers"
        key = uuid4()
        payload = _transfer_payload(ids, key)

        first = client.post(url, json=payload)
        assert first.status_code == 201, first.text
        replay = client.post(url, json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]

        changed = client.post(url, json={**payload, "quantity": "3.000"})
        assert changed.status_code == 409, changed.text

        with TestSession() as session:
            requests = list(session.scalars(select(InventoryOperationRequest)).all())
            movements = list(session.scalars(select(InventoryMovement).where(
                InventoryMovement.movement_type == "TRANSFER"
            )).all())
            assert len(requests) == 1
            assert requests[0].status == "COMPLETED"
            assert requests[0].movement_id == movements[0].id
            assert len(movements) == 1

        inbox = client.get(
            f"/companies/{ids['company_id']}/inventory/operation-requests",
            params={"status": "COMPLETED", "limit": 10},
        )
        assert inbox.status_code == 200, inbox.text
        assert len(inbox.json()) == 1
        assert inbox.json()[0]["idempotency_key"] == str(key)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_failed_business_operation_is_recorded_and_never_blindly_retried():
    engine, TestSession, ids = _context()
    try:
        client = TestClient(app)
        url = f"/companies/{ids['company_id']}/inventory/transfers"
        key = uuid4()
        payload = _transfer_payload(ids, key)
        payload["quantity"] = "99.000"

        failed = client.post(url, json=payload)
        assert failed.status_code == 422, failed.text
        retry = client.post(url, json=payload)
        assert retry.status_code == 409, retry.text

        with TestSession() as session:
            row = session.scalar(select(InventoryOperationRequest))
            assert row is not None
            assert row.status == "FAILED"
            assert row.failure_code == "VALIDATION_FAILED"
            assert row.movement_id is None
            assert session.scalar(select(InventoryMovement).where(
                InventoryMovement.movement_type == "TRANSFER"
            )) is None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_pre_registry_legacy_movement_is_linked_without_duplicate_write():
    engine, TestSession, ids = _context()
    try:
        key = uuid4()
        with TestSession() as session:
            legacy = InventoryMovement(
                company_id=ids["company_id"], site_id=ids["site_id"],
                product_id=ids["product_id"], movement_type="TRANSFER",
                from_location_id=ids["source_id"], to_location_id=ids["destination_id"],
                quantity=Decimal("2.000"), weight=Decimal("1.0000"),
                weight_unit_code="QIAN", reference_type="MANUAL_TRANSFER",
                reference_id=key, note="操作恢復登記測試",
            )
            session.add(legacy)
            session.commit()
            legacy_id = legacy.id

        client = TestClient(app)
        response = client.post(
            f"/companies/{ids['company_id']}/inventory/transfers",
            json=_transfer_payload(ids, key),
        )
        assert response.status_code == 200, response.text
        assert response.json()["id"] == str(legacy_id)

        with TestSession() as session:
            rows = list(session.scalars(select(InventoryMovement).where(
                InventoryMovement.movement_type == "TRANSFER"
            )).all())
            request = session.scalar(select(InventoryOperationRequest))
            assert len(rows) == 1
            assert request.status == "COMPLETED"
            assert request.movement_id == legacy_id
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
