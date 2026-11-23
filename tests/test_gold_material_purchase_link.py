from datetime import date
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
from app.models.purchase import Purchase
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
    db = TestSession()
    company = Company(code="GM-PO-TEST", name="金料採購關聯測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-CANCELLED-GOLD", order_date=date(2026, 11, 23),
        status="CANCELLED", currency_code="TWD",
    )
    db.add(purchase)
    db.commit()
    ids = company.id, site.id, supplier.id, purchase.id
    db.close()

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


def test_gold_settlement_rejects_cancelled_purchase_without_partial_writes():
    engine, TestSession, (company_id, site_id, supplier_id, purchase_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-CANCELLED-GOLD",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "10000.00",
        })
        assert bill.status_code == 201, bill.text

        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-CANCELLED-PO",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "20.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text

        rejected = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_id": str(purchase_id),
            "movement_no": "GM-DEL-CANCELLED-PO",
            "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "5.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "5000.00",
            }],
        })
        assert rejected.status_code == 422, rejected.text
        assert "狀態不允許折抵" in rejected.json()["detail"]

        balance = client.get(f"{gold_base}/balance", params={"site_id": str(site_id)})
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("20.0000")
        refreshed = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "OPEN"
        assert Decimal(refreshed.json()["paid_amount"]) == Decimal("0.00")

        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 1
        assert check.query(GoldMaterialSettlementAllocation).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
