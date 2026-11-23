from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales, sales_returns
from app.services.inventory import create_inventory_movement, get_stock_balance


def _context(code):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code=code, name="銷售流程測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code=f"{code}-001", barcode=f"{code}-BAR-001",
                      name="黃金戒指", gross_weight=Decimal("1.2000"), net_weight=Decimal("1.0000"),
                      weight_unit_code="QIAN", labor_fee=Decimal("300"))
    db.add_all([site, location, product])
    db.flush()
    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_all([
        GoldPrice(company_id=company.id, site_id=None, price_type="SELL", price_value=Decimal("12000"),
                  currency_code="TWD", unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
        GoldPrice(company_id=company.id, site_id=None, price_type="BUY", price_value=Decimal("11000"),
                  currency_code="TWD", unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
    ])
    db.commit()
    ids = (company.id, site.id, location.id, product.id)
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    app.dependency_overrides[sales_returns.get_db] = override_db
    return engine, TestSession, ids


def _cleanup(engine):
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()

def test_return_rejects_line_from_another_sale_without_partial_restocking():
    engine, TestSession, (company_id, site_id, location_id, product_id) = _context("CROSS-RETURN")
    db = TestSession()
    create_inventory_movement(db, company_id=company_id, site_id=site_id, product_id=product_id,
                               movement_type="RECEIPT", quantity=Decimal("2"), to_location_id=location_id,
                               weight=Decimal("2.0000"), weight_unit_code="QIAN")
    db.commit()
    db.close()
    try:
        client = TestClient(app)
        sales_created = []
        for sale_no in ("SO-CROSS-A", "SO-CROSS-B"):
            created = client.post(f"/companies/{company_id}/sales", json={
                "site_id": str(site_id), "sale_no": sale_no, "payment_method": "CASH",
                "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
            })
            assert created.status_code == 201, created.text
            sale = created.json()
            completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
            assert completed.status_code == 200, completed.text
            sales_created.append(sale)

        first, second = sales_created
        rejected = client.post(f"/companies/{company_id}/sales/{first['id']}/returns", json={
            "return_no": "RT-CROSS-INVALID",
            "sale_line_ids": [first["lines"][0]["id"], second["lines"][0]["id"]],
            "reason": "跨銷售單明細不得混用",
        })
        assert rejected.status_code == 422
        assert "不屬於指定銷售單" in rejected.json()["detail"]

        check = TestSession()
        from app.models.sale_return import SaleReturn, SaleReturnLine
        assert check.query(SaleReturn).count() == 0
        assert check.query(SaleReturnLine).count() == 0
        assert check.query(InventoryMovement).filter_by(reference_type="SALE_LINE").count() == 2
        assert check.query(InventoryMovement).filter_by(reference_type="SALE_RETURN_LINE").count() == 0
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("0")
        check.close()
    finally:
        _cleanup(engine)
