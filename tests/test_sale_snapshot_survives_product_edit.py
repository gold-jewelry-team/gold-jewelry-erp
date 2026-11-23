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


def test_return_uses_original_sale_snapshots_after_product_master_is_edited():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    try:
        company = Company(code="SNAPSHOT-RETURN", name="銷售快照退貨測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        location = StorageLocation(site_id=site.id, code="SAFE", name="原保險櫃", location_type="SAFE")
        product = Product(
            company_id=company.id, product_code="SNAP-OLD-001", barcode="SNAP-BAR-OLD",
            name="原始黃金戒指", gross_weight=Decimal("1.2500"),
            net_weight=Decimal("1.1250"), weight_unit_code="QIAN", labor_fee=Decimal("300"),
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
            movement_type="RECEIPT", quantity=Decimal("1"), to_location_id=location.id,
            weight=Decimal("1.1250"), weight_unit_code="QIAN",
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
    app.dependency_overrides[sales_returns.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id), "sale_no": "SO-SNAPSHOT-001", "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        line = sale["lines"][0]
        assert line["product_code_snapshot"] == "SNAP-OLD-001"
        assert line["barcode_snapshot"] == "SNAP-BAR-OLD"
        assert line["product_name_snapshot"] == "原始黃金戒指"
        assert line["net_weight"] == "1.1250"
        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text

        edit = TestSession()
        changed = edit.get(Product, product_id)
        changed.product_code = "SNAP-NEW-999"
        changed.barcode = "SNAP-BAR-NEW"
        changed.name = "修改後商品名稱"
        changed.net_weight = Decimal("0.9000")
        edit.commit()
        edit.close()

        returned = client.post(f"/companies/{company_id}/sales/{sale['id']}/returns", json={
            "return_no": "RT-SNAPSHOT-001", "sale_line_ids": [line["id"]],
            "reason": "驗證歷史商品快照",
        })
        assert returned.status_code == 201, returned.text
        return_line = returned.json()["lines"][0]
        assert return_line["product_code_snapshot"] == "SNAP-OLD-001"
        assert return_line["barcode_snapshot"] == "SNAP-BAR-OLD"
        assert return_line["product_name_snapshot"] == "原始黃金戒指"
        assert return_line["net_weight"] == "1.1250"
        assert return_line["source_location_id"] == str(location_id)

        check = TestSession()
        movement = check.query(InventoryMovement).filter_by(reference_type="SALE_RETURN_LINE").one()
        assert movement.reference_id == return_line["id"]
        assert movement.to_location_id == location_id
        assert movement.weight == Decimal("1.1250")
        assert movement.weight_unit_code == "QIAN"
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("1")
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
