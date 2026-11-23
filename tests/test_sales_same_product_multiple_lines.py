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


def test_same_product_on_two_sale_lines_creates_two_linked_deductions():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    try:
        company = Company(code="SAME-PRODUCT", name="同商品多件銷售測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        product = Product(
            company_id=company.id, product_code="SAME-001", barcode="SAME-BAR-001",
            name="同款黃金商品", gross_weight=Decimal("1.2000"),
            net_weight=Decimal("1.0000"), weight_unit_code="QIAN", labor_fee=Decimal("300"),
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
            movement_type="RECEIPT", quantity=Decimal("2"), to_location_id=location.id,
            weight=Decimal("2.0000"), weight_unit_code="QIAN",
        )
        session.commit()
        company_id, site_id, product_id, location_id = company.id, site.id, product.id, location.id
    finally:
        session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id), "sale_no": "SO-SAME-001", "payment_method": "CASH",
            "lines": [
                {"product_id": str(product_id), "source_location_id": str(location_id)},
                {"product_id": str(product_id), "source_location_id": str(location_id)},
            ],
        })
        assert response.status_code == 201, response.text
        sale = response.json()
        assert len(sale["lines"]) == 2
        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text

        check = TestSession()
        movements = check.query(InventoryMovement).filter_by(reference_type="SALE_LINE").all()
        assert len(movements) == 2
        assert {str(m.reference_id) for m in movements} == {line["id"] for line in sale["lines"]}
        assert {m.product_id for m in movements} == {product_id}
        assert all(m.movement_type == "SALE" and m.quantity == Decimal("1") for m in movements)
        assert all(m.weight == Decimal("1.0000") and m.weight_unit_code == "QIAN" for m in movements)
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("0")
        assert check.get(Sale, sale["id"]).status == "COMPLETED"
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
