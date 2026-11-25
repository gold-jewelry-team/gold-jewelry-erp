from datetime import date
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
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.routers import inventory, product_master, purchases
from app.services.purchasing import receive_purchase_line


def _setup_receipt_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()

    company = Company(code="RECEIPT-IDEMP", name="到貨重送測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-RETRY", name="重送測試供應商")
    db.add_all([site, supplier])
    db.flush()
    safe = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    show = StorageLocation(
        site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
    )
    product = Product(
        company_id=company.id,
        product_code="RECEIPT-IDEMP-001",
        barcode="RECEIPT-IDEMP-001",
        name="分批驗收測試戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.2000"),
        weight_unit_code="QIAN",
    )
    db.add_all([safe, show, product])
    db.flush()
    purchase = Purchase(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        purchase_no="PO-RECEIPT-IDEMP-001",
        order_date=date(2026, 11, 23),
        status="ORDERED",
        currency_code="TWD",
    )
    db.add(purchase)
    db.flush()
    line = PurchaseLine(
        purchase_id=purchase.id,
        product_id=product.id,
        quantity=Decimal("2"),
        received_quantity=Decimal("0"),
        weight=Decimal("1.2000"),
        weight_unit_code="QIAN",
        unit_cost=Decimal("12000.00"),
    )
    db.add(line)
    db.commit()
    ids = {
        "company_id": company.id,
        "site_id": site.id,
        "safe_id": safe.id,
        "show_id": show.id,
        "product_id": product.id,
        "purchase_id": purchase.id,
        "line_id": line.id,
    }
    db.close()

    def override_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[purchases.get_db] = override_db
    app.dependency_overrides[product_master.get_db] = override_db
    app.dependency_overrides[inventory.get_db] = override_db
    return engine, test_session, TestClient(app), ids


def test_purchase_receipt_retry_is_exactly_once_and_label_lots_still_trace():
    engine, test_session, client, ids = _setup_receipt_client()
    company_id = ids["company_id"]
    purchase_id = ids["purchase_id"]
    line_id = ids["line_id"]
    key = str(uuid4())
    first_payload = {
        "purchase_line_id": str(line_id),
        "location_id": str(ids["safe_id"]),
        "received_quantity": "1.000",
        "idempotency_key": key,
    }
    url = f"/companies/{company_id}/purchases/{purchase_id}/receive"
    try:
        first = client.post(url, json=first_payload)
        replay = client.post(url, json=first_payload)

        assert first.status_code == 200, first.text
        assert first.json()["status"] == "PARTIALLY_RECEIVED"
        assert replay.status_code == 200, replay.text
        assert replay.json()["status"] == "PARTIALLY_RECEIVED"

        changed_replay = client.post(url, json={**first_payload, "received_quantity": "2.000"})
        assert changed_replay.status_code == 409, changed_replay.text
        assert "驗收識別碼" in changed_replay.json()["detail"]

        second_payload = {
            "purchase_line_id": str(line_id),
            "location_id": str(ids["show_id"]),
            "received_quantity": "1.000",
            "idempotency_key": str(uuid4()),
        }
        second = client.post(url, json=second_payload)
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "RECEIVED"

        # A delayed retry after the purchase is fully received still returns
        # the first receipt instead of failing the remaining-quantity check.
        late_replay = client.post(url, json=first_payload)
        assert late_replay.status_code == 200, late_replay.text
        assert late_replay.json()["status"] == "RECEIVED"

        verify = test_session()
        line = verify.get(PurchaseLine, line_id)
        movements = verify.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.reference_id == line_id,
            InventoryMovement.movement_type == "RECEIPT",
        ).order_by(InventoryMovement.created_at, InventoryMovement.id)).all()
        assert line.received_quantity == Decimal("2.000")
        assert len(movements) == 2
        assert all(movement.reference_type.startswith("PR-") for movement in movements)
        assert all(len(movement.reference_type) <= 30 for movement in movements)
        assert sum((movement.quantity for movement in movements), Decimal("0")) == Decimal("2")
        assert sum((movement.weight for movement in movements), Decimal("0")) == Decimal("1.2000")
        verify.close()

        lots = client.get(
            f"/companies/{company_id}/products/{ids['product_id']}/label-lots"
        )
        assert lots.status_code == 200, lots.text
        assert len(lots.json()) == 2
        assert {lot["location_code"] for lot in lots.json()} == {"SAFE", "SHOW"}
        assert sum((Decimal(lot["weight"]) for lot in lots.json()), Decimal("0")) == Decimal("1.2000")

        history = client.get(
            f"/companies/{company_id}/inventory/movements",
            params={"product_id": str(ids["product_id"]), "movement_type": "RECEIPT"},
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 2
        assert all(row["reference_type"] == "PURCHASE_LINE" for row in history.json())
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_keyed_receipt_weight_allocation_includes_legacy_unkeyed_receipts():
    engine, test_session, client, ids = _setup_receipt_client()
    db = test_session()
    try:
        line = db.get(PurchaseLine, ids["line_id"])
        first = receive_purchase_line(
            db,
            purchase_id=ids["purchase_id"],
            purchase_line_id=ids["line_id"],
            location_id=ids["safe_id"],
            received_quantity=Decimal("1.000"),
        )
        db.commit()
        assert first.reference_type == "PURCHASE_LINE"

        second = receive_purchase_line(
            db,
            purchase_id=ids["purchase_id"],
            purchase_line_id=ids["line_id"],
            location_id=ids["show_id"],
            received_quantity=Decimal("1.000"),
            idempotency_key=uuid4(),
        )
        db.commit()

        assert second.reference_type.startswith("PR-")
        assert first.weight == Decimal("0.6000")
        assert second.weight == Decimal("0.6000")
        assert sum((first.weight, second.weight), Decimal("0")) == Decimal("1.2000")
        assert line.received_quantity == Decimal("2.000")
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()

def test_purchase_receipt_api_requires_an_idempotency_key():
    engine, test_session, client, ids = _setup_receipt_client()
    try:
        url = f"/companies/{ids['company_id']}/purchases/{ids['purchase_id']}/receive"
        response = client.post(url, json={
            "purchase_line_id": str(ids["line_id"]),
            "location_id": str(ids["safe_id"]),
            "received_quantity": "1.000",
        })
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert any(
            item.get("loc", [])[-1:] == ["idempotency_key"]
            and item.get("type") == "missing"
            for item in detail
        )

        verify = test_session()
        line = verify.get(PurchaseLine, ids["line_id"])
        assert line.received_quantity == Decimal("0.000")
        assert verify.query(InventoryMovement).filter(
            InventoryMovement.movement_type == "RECEIPT"
        ).count() == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

