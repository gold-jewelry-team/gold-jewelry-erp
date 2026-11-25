from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
from app.services.inventory import get_stock_balance


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as session:
        company = Company(code="TRANSFER-IDEMP", name="調撥防重複測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        source = StorageLocation(
            site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
        )
        destination = StorageLocation(
            site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
        )
        product = Product(
            company_id=company.id,
            product_code="TRANSFER-IDEMP-001",
            name="調撥重送測試金戒",
            gross_weight=Decimal("1.2000"),
            net_weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
        )
        session.add_all([source, destination, product])
        session.flush()
        session.add(InventoryMovement(
            company_id=company.id,
            site_id=site.id,
            product_id=product.id,
            movement_type="RECEIPT",
            to_location_id=source.id,
            quantity=Decimal("5.000"),
            weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
            reference_type="TEST_RECEIPT",
            note="測試期初入庫",
        ))
        ids = {
            "company_id": company.id,
            "site_id": site.id,
            "source_id": source.id,
            "destination_id": destination.id,
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


def _payload(ids, key):
    return {
        "site_id": str(ids["site_id"]),
        "product_id": str(ids["product_id"]),
        "from_location_id": str(ids["source_id"]),
        "to_location_id": str(ids["destination_id"]),
        "quantity": "2.000",
        "weight": "1.0000",
        "weight_unit_code": "QIAN",
        "note": "從保險櫃調至展示櫃",
        "idempotency_key": str(key),
    }


def test_manual_transfer_exact_retry_returns_original_and_conflict_does_not_move_stock_twice():
    engine, TestSession, ids = _context()
    try:
        client = TestClient(app)
        url = f"/companies/{ids['company_id']}/inventory/transfers"
        key = uuid4()
        payload = _payload(ids, key)

        first = client.post(url, json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["reference_type"] == "MANUAL_TRANSFER"
        assert first.json()["reference_id"] == str(key)

        replay = client.post(url, json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]

        changed = {**payload, "quantity": "3.000"}
        conflict = client.post(url, json=changed)
        assert conflict.status_code == 409, conflict.text

        verify = TestSession()
        rows = list(verify.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == ids["company_id"]
        )).all())
        transfer_rows = [row for row in rows if row.movement_type == "TRANSFER"]
        assert len(rows) == 2
        assert len(transfer_rows) == 1
        assert transfer_rows[0].reference_id == key
        assert get_stock_balance(
            verify, product_id=ids["product_id"], location_id=ids["source_id"]
        ) == Decimal("3.000")
        assert get_stock_balance(
            verify, product_id=ids["product_id"], location_id=ids["destination_id"]
        ) == Decimal("2.000")
        assert (
            get_stock_balance(verify, product_id=ids["product_id"], location_id=ids["source_id"])
            + get_stock_balance(verify, product_id=ids["product_id"], location_id=ids["destination_id"])
        ) == Decimal("5.000")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_transfer_api_requires_key_and_does_not_write_without_one():
    engine, TestSession, ids = _context()
    try:
        client = TestClient(app)
        url = f"/companies/{ids['company_id']}/inventory/transfers"
        payload = _payload(ids, uuid4())
        payload.pop("idempotency_key")
        response = client.post(url, json=payload)
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert any(
            item.get("loc", [])[-1:] == ["idempotency_key"]
            and item.get("type") == "missing"
            for item in detail
        )

        verify = TestSession()
        rows = list(verify.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == ids["company_id"]
        )).all())
        assert len(rows) == 1
        assert rows[0].movement_type == "RECEIPT"
        assert get_stock_balance(
            verify, product_id=ids["product_id"], location_id=ids["source_id"]
        ) == Decimal("5.000")
        assert get_stock_balance(
            verify, product_id=ids["product_id"], location_id=ids["destination_id"]
        ) == Decimal("0")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
