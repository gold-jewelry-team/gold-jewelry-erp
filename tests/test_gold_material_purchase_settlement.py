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
    company = Company(code="GM-PO-VALID", name="採購金料折抵測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-GOLD-VALID", order_date=date(2026, 11, 23),
        status="ORDERED", currency_code="TWD",
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


def test_valid_purchase_linked_gold_settlement_uses_purchase_supplier_and_pays_bill():
    engine, TestSession, (company_id, site_id, supplier_id, purchase_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_id": str(purchase_id),
            "bill_no": "INV-GOLD-VALID-PO",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "5000.00",
        })
        assert bill.status_code == 201, bill.text
        assert bill.json()["purchase_id"] == str(purchase_id)

        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-VALID-PO",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "10.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text

        settlement = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "purchase_id": str(purchase_id),
            "movement_no": "GM-DEL-VALID-PO",
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
        assert settlement.status_code == 201, settlement.text
        assert settlement.json()["supplier_id"] == str(supplier_id)
        assert settlement.json()["purchase_id"] == str(purchase_id)
        assert settlement.json()["valuation_amount"] == "5000.00"

        refreshed = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "PAID"
        assert Decimal(refreshed.json()["paid_amount"]) == Decimal("5000.00")
        assert Decimal(refreshed.json()["outstanding_amount"]) == Decimal("0.00")

        check = TestSession()
        movement = check.query(GoldMaterialMovement).filter_by(
            movement_no="GM-DEL-VALID-PO"
        ).one()
        assert movement.purchase_id == purchase_id
        assert movement.supplier_id == supplier_id
        assert check.query(GoldMaterialSettlementAllocation).count() == 1
        stored_bill = check.get(SupplierBill, __import__("uuid").UUID(bill.json()["id"]))
        assert stored_bill.status == "PAID"
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

def test_cash_payment_then_gold_offset_completes_same_purchase_bill():
    engine, TestSession, (company_id, site_id, supplier_id, purchase_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_id": str(purchase_id),
            "bill_no": "INV-MIXED-SETTLEMENT",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "5000.00",
        })
        assert bill.status_code == 201, bill.text

        cash_payment = client.post(f"{payable_base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-MIXED-SETTLEMENT",
            "payment_method": "TRANSFER",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "2000.00",
            }],
        })
        assert cash_payment.status_code == 201, cash_payment.text
        after_cash = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert after_cash.status_code == 200, after_cash.text
        assert after_cash.json()["status"] == "PARTIALLY_PAID"
        assert Decimal(after_cash.json()["paid_amount"]) == Decimal("2000.00")
        assert Decimal(after_cash.json()["outstanding_amount"]) == Decimal("3000.00")

        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-MIXED-SETTLEMENT",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "3.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text

        gold_settlement = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "purchase_id": str(purchase_id),
            "movement_no": "GM-DEL-MIXED-SETTLEMENT",
            "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "3.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "3000.00",
            }],
        })
        assert gold_settlement.status_code == 201, gold_settlement.text
        assert Decimal(gold_settlement.json()["valuation_amount"]) == Decimal("3000.00")

        final_bill = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert final_bill.status_code == 200, final_bill.text
        assert final_bill.json()["status"] == "PAID"
        assert Decimal(final_bill.json()["paid_amount"]) == Decimal("5000.00")
        assert Decimal(final_bill.json()["outstanding_amount"]) == Decimal("0.00")

        check = TestSession()
        stored_bill = check.get(SupplierBill, __import__("uuid").UUID(bill.json()["id"]))
        assert stored_bill.status == "PAID"
        assert sum((a.amount for a in stored_bill.allocations), Decimal("0")) == Decimal("2000.00")
        assert sum((a.amount for a in stored_bill.gold_allocations), Decimal("0")) == Decimal("3000.00")
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

