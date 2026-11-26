from datetime import datetime, timedelta, timezone
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
from app.models.gold_price import GoldPrice
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_repeating_complete_action_returns_success_without_second_stock_movement():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="SALE-REPEAT", name="重複完成銷售測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code="SALE-REPEAT-001", barcode="SALE-REPEAT-001",
                      name="黃金戒指", gross_weight=Decimal("1.2000"), net_weight=Decimal("1.0000"),
                      weight_unit_code="QIAN", labor_fee=Decimal("300"))
    db.add_all([location, product])
    db.flush()
    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_all([
        GoldPrice(company_id=company.id, site_id=None, price_type="SELL", price_value=Decimal("12000"),
                  currency_code="TWD", unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
        GoldPrice(company_id=company.id, site_id=None, price_type="BUY", price_value=Decimal("11000"),
                  currency_code="TWD", unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
    ])
    create_inventory_movement(db, company_id=company.id, site_id=site.id, product_id=product.id,
                              movement_type="RECEIPT", quantity=Decimal("1"), to_location_id=location.id,
                              weight=Decimal("1.0000"), weight_unit_code="QIAN", reference_type="TEST")
    db.commit()
    company_id, site_id, location_id, product_id = company.id, site.id, location.id, product.id
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
        created = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id), "sale_no": "SO-REPEAT-COMPLETE", "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert created.status_code == 201, created.text
        sale_id = created.json()["id"]
        first = client.post(f"/companies/{company_id}/sales/{sale_id}/complete")
        assert first.status_code == 200, first.text
        second = client.post(f"/companies/{company_id}/sales/{sale_id}/complete")
        assert second.status_code == 200, second.text
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["status"] == "COMPLETED"
        assert second.json()["completed_at"] == first.json()["completed_at"]

        check = TestSession()
        sale = check.get(Sale, UUID(sale_id))
        assert sale.status == "COMPLETED"
        assert check.query(InventoryMovement).filter_by(reference_type="SALE_LINE").count() == 1
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("0")
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
