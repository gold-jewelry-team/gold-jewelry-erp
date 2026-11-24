from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.gold_material import GoldMaterialMovement, GoldMaterialSettlementAllocation
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill
from app.routers import gold_material, supplier_payables


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as session:
        company = Company(code="GM-IDEMPOTENCY", name="金料重送測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
        session.add_all([site, supplier])
        session.flush()
        ids = (company.id, site.id, supplier.id)
        session.commit()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[gold_material.get_db] = override_db
    app.dependency_overrides[supplier_payables.get_db] = override_db
    return engine, TestSession, ids


def _movement_payload(site_id, movement_no, **overrides):
    payload = {
        "site_id": str(site_id),
        "movement_no": movement_no,
        "movement_type": "OPENING",
        "source_type": "OPENING_BALANCE",
        "purity_label": "9999",
        "purity_ratio": "0.999900",
        "gross_weight": "20.0000",
        "loss_weight": "0",
        "weight_unit_code": "G",
        "gold_price_value": "3000.00",
        "gold_price_unit_code": "G",
        "deduction_amount": "0",
        "allocations": [],
        "note": "期初金料",
    }
    payload.update(overrides)
    return payload


def test_gold_material_exact_retry_returns_original_and_mismatch_conflicts():
    engine, TestSession, (company_id, site_id, _supplier_id) = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/gold-material"
        payload = _movement_payload(site_id, "GM-IDEM-OPEN-001")

        created = client.post(f"{base}/movements", json=payload)
        assert created.status_code == 201, created.text

        retried = client.post(f"{base}/movements", json=payload)
        assert retried.status_code == 200, retried.text
        assert retried.json()["id"] == created.json()["id"]

        changed = {**payload, "gross_weight": "21.0000"}
        conflict = client.post(f"{base}/movements", json=changed)
        assert conflict.status_code == 409, conflict.text
        assert "已用於不同內容" in conflict.json()["detail"]

        balance = client.get(
            f"{base}/balance", params={"site_id": str(site_id)}
        )
        assert balance.status_code == 200, balance.text
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("19.9980")

        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 1
        assert check.query(GoldMaterialSettlementAllocation).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_delivery_exact_retry_does_not_repeat_gold_deduction_or_bill_settlement():
    engine, TestSession, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-GM-IDEM-001",
            "bill_date": "2026-11-24",
            "currency_code": "TWD",
            "total_amount": "10000.00",
        })
        assert bill.status_code == 201, bill.text

        opening = client.post(
            f"{gold_base}/movements",
            json=_movement_payload(
                site_id,
                "GM-IDEM-OPEN-002",
                gross_weight="20.0000",
                purity_ratio="1.000000",
                note="期初金料",
            ),
        )
        assert opening.status_code == 201, opening.text

        delivery_payload = _movement_payload(
            site_id,
            "GM-IDEM-DEL-001",
            movement_type="SUPPLIER_DELIVERY",
            source_type="PURCHASE_SETTLEMENT",
            supplier_id=str(supplier_id),
            purity_ratio="1.000000",
            gross_weight="10.0000",
            gold_price_value="1000.00",
            allocations=[{
                "bill_id": bill.json()["id"],
                "amount": "10000.00",
            }],
            note="交付供應商折抵",
        )
        delivery = client.post(f"{gold_base}/movements", json=delivery_payload)
        assert delivery.status_code == 201, delivery.text
        assert delivery.json()["valuation_amount"] == "10000.00"

        settled_bill = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert settled_bill.status_code == 200, settled_bill.text
        assert settled_bill.json()["status"] == "PAID"
        assert settled_bill.json()["outstanding_amount"] == "0.00"

        retried = client.post(f"{gold_base}/movements", json=delivery_payload)
        assert retried.status_code == 200, retried.text
        assert retried.json()["id"] == delivery.json()["id"]

        balance = client.get(
            f"{gold_base}/balance", params={"site_id": str(site_id)}
        )
        assert balance.status_code == 200, balance.text
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("10.0000")

        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 2
        assert check.query(GoldMaterialSettlementAllocation).count() == 1
        stored_bill = check.get(SupplierBill, bill.json()["id"])
        assert stored_bill.paid_amount == Decimal("10000.00")
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
