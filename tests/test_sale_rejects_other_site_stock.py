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
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_sale_api_rejects_inventory_location_from_another_site():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="SALE-SITE-SCOPE", name="銷售跨據點限制測試")
    db.add(company)
    db.flush()
    sale_site = Site(company_id=company.id, code="MAIN", name="總店")
    stock_site = Site(company_id=company.id, code="BRANCH", name="分店")
    db.add_all([sale_site, stock_site])
    db.flush()
    foreign_location = StorageLocation(
        site_id=stock_site.id, code="SAFE-B", name="分店保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id,
        product_code="SALE-SITE-SCOPE-001",
        barcode="SALE-SITE-SCOPE-BAR-001",
        name="跨據點銷售測試戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    db.add_all([foreign_location, product])
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
        site_id=stock_site.id,
        product_id=product.id,
        movement_type="RECEIPT",
        quantity=Decimal("1"),
        to_location_id=foreign_location.id,
        weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        reference_type="TEST-RECEIPT",
    )
    db.commit()
    company_id, sale_site_id = company.id, sale_site.id
    location_id, product_id = foreign_location.id, product.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    try:
        client = TestClient(app)
        rejected = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(sale_site_id),
            "sale_no": "SO-CROSS-SITE-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert rejected.status_code == 422, rejected.text
        assert "不屬於銷售據點" in rejected.json()["detail"]

        verify = TestSession()
        assert verify.query(Sale).filter_by(company_id=company_id).count() == 0
        assert verify.query(InventoryMovement).filter_by(
            reference_type="SALE_LINE"
        ).count() == 0
        assert get_stock_balance(
            verify, product_id=product_id, location_id=location_id
        ) == Decimal("1")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
