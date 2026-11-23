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
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales, sales_returns
from app.services.daily_closing import create_daily_closing
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_return_api_rejects_return_after_daily_close_without_restocking():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="RETURN-CLOSED-API", name="日結後退貨 API 測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id,
        product_code="RETURN-CLOSED-001",
        barcode="RETURN-CLOSED-BAR-001",
        name="日結後退貨測試戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    db.add_all([site, location, product])
    db.flush()
    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_all([
        GoldPrice(
            company_id=company.id, site_id=None, price_type="SELL",
            price_value=Decimal("12000"), currency_code="TWD",
            unit_code="QIAN", effective_at=effective_at, source="MANUAL",
        ),
        GoldPrice(
            company_id=company.id, site_id=None, price_type="BUY",
            price_value=Decimal("11000"), currency_code="TWD",
            unit_code="QIAN", effective_at=effective_at, source="MANUAL",
        ),
    ])
    create_inventory_movement(
        db,
        company_id=company.id,
        site_id=site.id,
        product_id=product.id,
        movement_type="RECEIPT",
        quantity=Decimal("1"),
        to_location_id=location.id,
        weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        reference_type="TEST-RECEIPT",
    )
    db.commit()
    company_id, site_id = company.id, site.id
    product_id, location_id = product.id, location.id
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
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-CLOSED-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        completed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        close_session = TestSession()
        create_daily_closing(
            close_session,
            company_id=company_id,
            site_id=site_id,
            business_date=datetime.now().date(),
        )
        close_session.commit()
        close_session.close()

        rejected = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-CLOSED-001",
                "sale_line_ids": [sale["lines"][0]["id"]],
                "reason": "日結後不允許新增退貨",
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert "已結帳" in rejected.json()["detail"]

        verify = TestSession()
        assert verify.query(SaleReturn).count() == 0
        assert verify.query(models.SaleReturnLine).count() == 0
        assert verify.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).count() == 0
        assert get_stock_balance(
            verify, product_id=product_id, location_id=location_id
        ) == Decimal("0")
        persisted_sale = verify.get(Sale, sale["id"])
        assert persisted_sale.status == "COMPLETED"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
