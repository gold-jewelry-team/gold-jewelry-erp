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
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.gold_material import GoldMaterialMovement, GoldMaterialSettlementAllocation
from app.models.supplier_payable import SupplierBill, SupplierPayment
from app.routers import gold_material, supplier_payables


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="GM-TEST", name="金料折抵測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    session.add_all([site, supplier])
    session.commit()
    ids = (company.id, site.id, supplier.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[gold_material.get_db] = override_db
    app.dependency_overrides[supplier_payables.get_db] = override_db
    return engine, TestSession, ids


def test_supplier_gold_delivery_reduces_fine_gold_stock_and_supplier_payable():
    engine, TestSession, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-GOLD-001",
            "bill_date": "2026-11-20",
            "currency_code": "TWD",
            "total_amount": "30000.00",
        })
        assert bill.status_code == 201, bill.text

        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-001",
            "movement_type": "OPENING",
            "source_type": "OPENING_BALANCE",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "10.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text
        assert opening.json()["fine_gold_weight_g"] == "9.9990"
        assert opening.json()["valuation_amount"] == "29997.00"

        delivery = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "movement_no": "GM-DEL-001",
            "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "5.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "14998.50",
            }],
        })
        assert delivery.status_code == 201, delivery.text
        assert delivery.json()["valuation_amount"] == "14998.50"
        assert len(delivery.json()["allocations"]) == 1

        balance = client.get(f"{gold_base}/balance", params={"site_id": str(site_id)})
        assert balance.status_code == 200, balance.text
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("4.9995")

        refreshed_bill = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert refreshed_bill.status_code == 200, refreshed_bill.text
        assert refreshed_bill.json()["paid_amount"] == "14998.50"
        assert refreshed_bill.json()["outstanding_amount"] == "15001.50"
        assert refreshed_bill.json()["status"] == "PARTIALLY_PAID"

        cash_overpay = client.post(f"{payable_base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-GOLD-OVER",
            "payment_method": "TRANSFER",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "15001.51",
            }],
        })
        assert cash_overpay.status_code == 422
        assert "未付餘額" in cash_overpay.json()["detail"]

        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 2
        assert check.query(GoldMaterialSettlementAllocation).count() == 1
        stored_bill = check.get(SupplierBill, UUID(bill.json()["id"]))
        assert stored_bill.paid_amount == Decimal("14998.50")
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_gold_delivery_rejects_insufficient_stock_without_partial_writes():
    engine, TestSession, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        gold_base = f"/companies/{company_id}/gold-material"
        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-002",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "2.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text

        delivery = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "movement_no": "GM-DEL-002",
            "movement_type": "ADJUSTMENT_OUT",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "3.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert delivery.status_code == 422
        assert "金料庫存不足" in delivery.json()["detail"]

        balance = client.get(f"{gold_base}/balance", params={"site_id": str(site_id)})
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("1.9998")
        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_gold_and_cash_settlements_together_complete_supplier_bill():
    engine, TestSession, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-GOLD-CASH-COMBINED",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "30000.00",
        })
        assert bill.status_code == 201, bill.text

        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-COMBINED",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "10.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text

        delivery = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "movement_no": "GM-DEL-COMBINED",
            "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "2.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "5999.40",
            }],
        })
        assert delivery.status_code == 201, delivery.text

        after_gold = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert after_gold.status_code == 200, after_gold.text
        assert after_gold.json()["status"] == "PARTIALLY_PAID"
        assert Decimal(after_gold.json()["paid_amount"]) == Decimal("5999.40")
        assert Decimal(after_gold.json()["outstanding_amount"]) == Decimal("24000.60")

        cash = client.post(f"{payable_base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-GOLD-CASH-COMBINED",
            "payment_method": "TRANSFER",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "24000.60",
            }],
        })
        assert cash.status_code == 201, cash.text

        completed = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "PAID"
        assert Decimal(completed.json()["paid_amount"]) == Decimal("30000.00")
        assert Decimal(completed.json()["outstanding_amount"]) == Decimal("0.00")

        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 2
        assert check.query(GoldMaterialSettlementAllocation).count() == 1
        assert check.query(SupplierPayment).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_gold_settlement_completes_remaining_balance_after_cash_payment():
    engine, TestSession, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        payable_base = f"/companies/{company_id}/supplier-payables"
        gold_base = f"/companies/{company_id}/gold-material"

        bill = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-CASH-THEN-GOLD",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "30000.00",
        })
        assert bill.status_code == 201, bill.text

        cash = client.post(f"{payable_base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-CASH-BEFORE-GOLD",
            "payment_method": "TRANSFER",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "10000.00",
            }],
        })
        assert cash.status_code == 201, cash.text

        after_cash = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert after_cash.status_code == 200, after_cash.text
        assert after_cash.json()["status"] == "PARTIALLY_PAID"
        assert Decimal(after_cash.json()["paid_amount"]) == Decimal("10000.00")
        assert Decimal(after_cash.json()["outstanding_amount"]) == Decimal("20000.00")

        opening = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-OPEN-CASH-GOLD",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "30.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text

        gold = client.post(f"{gold_base}/movements", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "movement_no": "GM-DEL-CASH-GOLD",
            "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "20.0000",
            "loss_weight": "0",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "20000.00",
            }],
        })
        assert gold.status_code == 201, gold.text

        completed = client.get(f"{payable_base}/bills/{bill.json()['id']}")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "PAID"
        assert Decimal(completed.json()["paid_amount"]) == Decimal("30000.00")
        assert Decimal(completed.json()["outstanding_amount"]) == Decimal("0.00")

        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 2
        assert check.query(GoldMaterialSettlementAllocation).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
