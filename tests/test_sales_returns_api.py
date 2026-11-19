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
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales, sales_returns
from app.services.inventory import create_inventory_movement, get_stock_balance


def _return_test_context(code: str):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code=code, name="退貨測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(
        company_id=company.id,
        product_code=f"{code}-G-001",
        barcode=f"{code}-BAR-001",
        name="退貨測試黃金戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    session.add_all([location, product])
    session.flush()
    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.add_all([
        GoldPrice(company_id=company.id, site_id=None, price_type="SELL",
                  price_value=Decimal("12000"), currency_code="TWD",
                  unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
        GoldPrice(company_id=company.id, site_id=None, price_type="BUY",
                  price_value=Decimal("11000"), currency_code="TWD",
                  unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
    ])
    create_inventory_movement(
        session, company_id=company.id, site_id=site.id, product_id=product.id,
        movement_type="RECEIPT", quantity=Decimal("1"),
        to_location_id=location.id, weight=Decimal("1.0000"),
        weight_unit_code="QIAN", reference_type="TEST",
    )
    session.commit()
    ids = (company.id, site.id, product.id, location.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    app.dependency_overrides[sales_returns.get_db] = override_db
    return engine, TestSession, ids


def test_completed_sale_return_restocks_item_and_records_signed_reversal():
    engine, TestSession, (company_id, site_id, product_id, location_id) = _return_test_context("RETURN-OK")
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-001",
            "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text
        line_id = sale["lines"][0]["id"]

        returned = client.post(f"/companies/{company_id}/sales/{sale['id']}/returns", json={
            "return_no": "RT-RETURN-001",
            "sale_line_ids": [line_id],
            "reason": "顧客退貨",
        })
        assert returned.status_code == 201, returned.text
        record = returned.json()
        assert record["settlement_reversal_amount"] == "-12300.00"
        assert record["lines"][0]["product_code_snapshot"] == "RETURN-OK-G-001"

        check = TestSession()
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("1")
        movements = list(check.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).all())
        assert len(movements) == 1
        assert movements[0].movement_type == "RETURN"
        assert movements[0].to_location_id == location_id
        check.close()

        duplicate = client.post(f"/companies/{company_id}/sales/{sale['id']}/returns", json={
            "return_no": "RT-RETURN-002",
            "sale_line_ids": [line_id],
        })
        assert duplicate.status_code == 422
        check = TestSession()
        assert check.query(SaleReturn).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_draft_sale_cannot_be_returned():
    engine, TestSession, (company_id, site_id, product_id, location_id) = _return_test_context("RETURN-DRAFT")
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-DRAFT",
            "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        returned = client.post(f"/companies/{company_id}/sales/{sale['id']}/returns", json={
            "return_no": "RT-DRAFT-001",
            "sale_line_ids": [sale["lines"][0]["id"]],
        })
        assert returned.status_code == 422
        check = TestSession()
        assert check.query(SaleReturn).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
