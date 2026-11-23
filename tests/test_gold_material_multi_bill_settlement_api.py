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
from app.models.gold_material import GoldMaterialMovement, GoldMaterialSettlementAllocation
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill
from app.routers import gold_material, supplier_payables


def test_one_gold_delivery_can_settle_multiple_supplier_bills_atomically():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="GM-MULTI-BILL", name="多帳單金料折抵測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="同一供應商")
    db.add_all([site, supplier])
    db.commit()
    company_id, site_id, supplier_id = company.id, site.id, supplier.id
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
    try:
        client = TestClient(app)
        payable = f"/companies/{company_id}/supplier-payables"
        gold = f"/companies/{company_id}/gold-material"
        bills = []
        for bill_no, amount in (
            ("INV-MULTI-GOLD-001", "2000.00"),
            ("INV-MULTI-GOLD-002", "3000.00"),
        ):
            created = client.post(f"{payable}/bills", json={
                "site_id": str(site_id),
                "supplier_id": str(supplier_id),
                "bill_no": bill_no,
                "bill_date": "2026-11-23",
                "currency_code": "TWD",
                "total_amount": amount,
            })
            assert created.status_code == 201, created.text
            bills.append(created.json())

        opening = client.post(f"{gold}/movements", json={
            "site_id": str(site_id),
            "movement_no": "GM-MULTI-OPEN",
            "movement_type": "OPENING",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "5.0000",
            "loss_weight": "0.0000",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0.00",
        })
        assert opening.status_code == 201, opening.text

        delivered = client.post(f"{gold}/movements", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "movement_no": "GM-MULTI-DELIVERY",
            "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT",
            "purity_label": "9999",
            "purity_ratio": "1.000000",
            "gross_weight": "5.0000",
            "loss_weight": "0.0000",
            "weight_unit_code": "G",
            "gold_price_value": "1000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0.00",
            "allocations": [
                {"bill_id": bills[0]["id"], "amount": "2000.00"},
                {"bill_id": bills[1]["id"], "amount": "3000.00"},
            ],
        })
        assert delivered.status_code == 201, delivered.text
        assert delivered.json()["valuation_amount"] == "5000.00"
        assert len(delivered.json()["allocations"]) == 2

        for expected_bill, expected_amount in zip(bills, ("2000.00", "3000.00")):
            refreshed = client.get(f"{payable}/bills/{expected_bill['id']}")
            assert refreshed.status_code == 200, refreshed.text
            assert refreshed.json()["status"] == "PAID"
            assert refreshed.json()["paid_amount"] == expected_amount
            assert refreshed.json()["outstanding_amount"] == "0.00"

        balance = client.get(f"{gold}/balance", params={"site_id": str(site_id)})
        assert balance.status_code == 200, balance.text
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("0.0000")

        verify = TestSession()
        movement = verify.query(GoldMaterialMovement).filter_by(
            movement_no="GM-MULTI-DELIVERY"
        ).one()
        allocations = verify.query(GoldMaterialSettlementAllocation).filter_by(
            movement_id=movement.id
        ).all()
        assert len(allocations) == 2
        assert sum((row.amount for row in allocations), Decimal("0")) == Decimal("5000.00")
        for bill in bills:
            stored = verify.get(SupplierBill, UUID(bill["id"]))
            assert stored.status == "PAID"
            assert stored.paid_amount == Decimal(bill["total_amount"])
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
