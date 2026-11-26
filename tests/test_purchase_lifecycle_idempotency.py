from datetime import date
from decimal import Decimal
from uuid import UUID

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
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.routers import purchases


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    company = Company(code="PO-RETRY", name="採購重試測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    supplier = Supplier(company_id=company.id, code="SUP-RETRY", name="測試供應商")
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id,
        product_code="PO-RETRY-001",
        name="測試黃金戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
    )
    db.add_all([site, supplier, location, product])
    db.commit()
    ids = (company.id, site.id, supplier.id, location.id, product.id)
    db.close()

    def override_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[purchases.get_db] = override_db
    return engine, test_session, ids


def _create_purchase(client, ids, purchase_no):
    company_id, site_id, supplier_id, _location_id, product_id = ids
    response = client.post(f"/companies/{company_id}/purchases", json={
        "site_id": str(site_id),
        "supplier_id": str(supplier_id),
        "purchase_no": purchase_no,
        "order_date": date.today().isoformat(),
        "currency_code": "TWD",
        "lines": [{
            "product_id": str(product_id),
            "quantity": "2",
            "weight": "2.0000",
            "weight_unit_code": "QIAN",
            "unit_cost": "12000.00",
        }],
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_purchase_submit_retry_is_idempotent_across_receiving_states():
    engine, test_session, ids = _context()
    try:
        client = TestClient(app)
        company_id, _site_id, _supplier_id, location_id, _product_id = ids
        purchase = _create_purchase(client, ids, "PO-RETRY-SUBMIT")
        purchase_id = purchase["id"]
        line_id = purchase["lines"][0]["id"]

        first_submit = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/submit"
        )
        assert first_submit.status_code == 200, first_submit.text
        assert first_submit.json()["status"] == "ORDERED"

        exact_retry = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/submit"
        )
        assert exact_retry.status_code == 200, exact_retry.text
        assert exact_retry.json()["status"] == "ORDERED"

        first_receipt = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/receive",
            json={
                "purchase_line_id": line_id,
                "location_id": str(location_id),
                "received_quantity": "1",
                "idempotency_key": "a5dc9d42-5e42-4fb8-9320-1f184f830001",
            },
        )
        assert first_receipt.status_code == 200, first_receipt.text
        assert first_receipt.json()["status"] == "PARTIALLY_RECEIVED"

        retry_after_progress = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/submit"
        )
        assert retry_after_progress.status_code == 200, retry_after_progress.text
        assert retry_after_progress.json()["status"] == "PARTIALLY_RECEIVED"

        second_receipt = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/receive",
            json={
                "purchase_line_id": line_id,
                "location_id": str(location_id),
                "received_quantity": "1",
                "idempotency_key": "a5dc9d42-5e42-4fb8-9320-1f184f830002",
            },
        )
        assert second_receipt.status_code == 200, second_receipt.text
        assert second_receipt.json()["status"] == "RECEIVED"

        retry_after_completion = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/submit"
        )
        assert retry_after_completion.status_code == 200, retry_after_completion.text
        assert retry_after_completion.json()["status"] == "RECEIVED"

        db = test_session()
        stored_purchase = db.get(Purchase, UUID(purchase_id))
        stored_line = db.get(PurchaseLine, UUID(line_id))
        movements = db.query(InventoryMovement).filter(
            InventoryMovement.reference_id == UUID(line_id),
            InventoryMovement.movement_type == "RECEIPT",
        ).all()
        assert stored_purchase.status == "RECEIVED"
        assert stored_line.received_quantity == Decimal("2.000")
        assert len(movements) == 2
        assert sum((row.quantity for row in movements), Decimal("0")) == Decimal("2")
        db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_purchase_cancel_retry_is_idempotent():
    engine, test_session, ids = _context()
    try:
        client = TestClient(app)
        company_id = ids[0]
        purchase = _create_purchase(client, ids, "PO-RETRY-CANCEL")
        purchase_id = purchase["id"]

        first_cancel = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/cancel"
        )
        assert first_cancel.status_code == 200, first_cancel.text
        assert first_cancel.json()["status"] == "CANCELLED"

        exact_retry = client.post(
            f"/companies/{company_id}/purchases/{purchase_id}/cancel"
        )
        assert exact_retry.status_code == 200, exact_retry.text
        assert exact_retry.json()["status"] == "CANCELLED"

        db = test_session()
        stored_purchase = db.get(Purchase, purchase_id)
        assert stored_purchase.status == "CANCELLED"
        assert db.query(InventoryMovement).filter(
            InventoryMovement.movement_type == "RECEIPT"
        ).count() == 0
        db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
