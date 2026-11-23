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
from app.routers import gold_material


def test_supplier_gold_delivery_requires_bill_allocation_without_stock_deduction():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="GM-ALLOC-REQ", name="折抵分攤必要性測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
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
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/gold-material"
        opening = client.post(f"{base}/movements", json={
            "site_id": str(site_id), "movement_no": "GM-OPEN-NO-ALLOC",
            "movement_type": "OPENING", "purity_label": "9999",
            "purity_ratio": "1.000000", "gross_weight": "10.0000",
            "loss_weight": "0", "weight_unit_code": "G",
            "gold_price_value": "1000.00", "gold_price_unit_code": "G",
            "deduction_amount": "0",
        })
        assert opening.status_code == 201, opening.text
        rejected = client.post(f"{base}/movements", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "movement_no": "GM-DEL-NO-ALLOC", "movement_type": "SUPPLIER_DELIVERY",
            "source_type": "PURCHASE_SETTLEMENT", "purity_label": "9999",
            "purity_ratio": "1.000000", "gross_weight": "2.0000",
            "loss_weight": "0", "weight_unit_code": "G",
            "gold_price_value": "1000.00", "gold_price_unit_code": "G",
            "deduction_amount": "0", "allocations": [],
        })
        assert rejected.status_code == 422, rejected.text
        assert "至少需要分攤至一張供應商帳單" in rejected.json()["detail"]
        balance = client.get(f"{base}/balance", params={"site_id": str(site_id)})
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("10.0000")
        check = TestSession()
        assert check.query(GoldMaterialMovement).count() == 1
        assert check.query(GoldMaterialSettlementAllocation).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
