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
from app.services.daily_closing import create_daily_closing
from zoneinfo import ZoneInfo


def test_sale_api_prices_snapshots_and_deducts_inventory_atomically():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()

    company = Company(code="SALE-STORE", name="銷售 API 測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(
        company_id=company.id,
        product_code="SALE-G-001",
        barcode="SALE-BAR-001",
        name="測試黃金戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    product2 = Product(
        company_id=company.id,
        product_code="SALE-G-002",
        barcode="SALE-BAR-002",
        name="測試黃金項鍊",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    session.add_all([location, product, product2])
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
        session,
        company_id=company.id,
        site_id=site.id,
        product_id=product.id,
        movement_type="RECEIPT",
        quantity=Decimal("1"),
        to_location_id=location.id,
        weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        reference_type="TEST",
    )
    session.commit()
    company_id, site_id, product_id, product2_id, location_id = (
        company.id, site.id, product.id, product2.id, location.id
    )
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
        created = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-API-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        assert sale["status"] == "DRAFT"
        assert sale["subtotal"] == "12300.00"
        assert sale["final_amount"] == "12300.00"
        assert sale["cash_amount"] == "12300.00"
        line = sale["lines"][0]
        assert line["product_code_snapshot"] == "SALE-G-001"
        assert line["sell_gold_price_value"] == "12000.0000"
        assert line["pricing_rule_version"] == "legacy-v1"

        mixed = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-API-MIXED-001",
            "payment_method": "CASH",
            "card_amount": "500",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert mixed.status_code == 201, mixed.text
        mixed_sale = mixed.json()
        assert mixed_sale["payment_method"] == "MIXED"
        assert mixed_sale["subtotal"] == "12300.00"
        assert mixed_sale["card_amount"] == "500.00"
        assert mixed_sale["cash_amount"] == "11800.00"
        assert mixed_sale["card_fee"] == "25.00"
        assert mixed_sale["final_amount"] == "12325.00"
        assert mixed_sale["lines"][0]["card_fee"] == "25.00"
        assert mixed_sale["lines"][0]["final_amount"] == "12325.00"

        multi = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-API-MULTI-001",
            "payment_method": "MIXED",
            "card_amount": "1010",
            "lines": [
                {"product_id": str(product_id), "source_location_id": str(location_id)},
                {"product_id": str(product2_id), "source_location_id": str(location_id)},
            ],
        })
        assert multi.status_code == 201, multi.text
        multi_sale = multi.json()
        assert multi_sale["subtotal"] == "24600.00"
        assert multi_sale["card_amount"] == "1010.00"
        assert multi_sale["cash_amount"] == "23590.00"
        assert multi_sale["card_fee"] == "51.00"
        assert multi_sale["final_amount"] == "24651.00"
        assert [line["card_fee"] for line in multi_sale["lines"]] == ["26.00", "25.00"]
        assert sum(Decimal(line["final_amount"]) for line in multi_sale["lines"]) == Decimal("24651.00")

        all_card = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-API-CARD-001",
            "payment_method": "CARD",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert all_card.status_code == 201, all_card.text
        card_sale = all_card.json()
        assert card_sale["card_amount"] == "12300.00"
        assert card_sale["cash_amount"] == "0.00"
        assert card_sale["card_fee"] == "615.00"
        assert card_sale["final_amount"] == "12915.00"

        completed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        check_session = TestSession()
        assert get_stock_balance(
            check_session, product_id=product_id, location_id=location_id
        ) == Decimal("0")
        movements = list(check_session.query(InventoryMovement).filter_by(
            reference_type="SALE_LINE"
        ).all())
        assert len(movements) == 1
        assert movements[0].movement_type == "SALE"
        check_session.close()

        duplicate_completion = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert duplicate_completion.status_code == 422

        # Closing the Taipei business day must block both new drafts and
        # completion of drafts created before the close.
        closing_session = TestSession()
        create_daily_closing(
            closing_session,
            company_id=company_id,
            site_id=site_id,
            business_date=datetime.now(ZoneInfo("Asia/Taipei")).date(),
        )
        closing_session.commit()
        closing_session.close()

        after_close = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-API-AFTER-CLOSE",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert after_close.status_code == 422
        assert "已結帳" in after_close.json()["detail"]

        blocked_completion = client.post(
            f"/companies/{company_id}/sales/{mixed_sale['id']}/complete"
        )
        assert blocked_completion.status_code == 422
        assert "已結帳" in blocked_completion.json()["detail"]

        final_check = TestSession()
        assert final_check.query(InventoryMovement).filter_by(reference_type="SALE_LINE").count() == 1
        assert final_check.query(Sale).filter_by(sale_no="SO-API-AFTER-CLOSE").count() == 0
        final_check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_sale_api_rejects_missing_effective_gold_price():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="NO-PRICE", name="缺金價測試")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code="NO-PRICE-1", name="測試商品",
                      gross_weight=Decimal("1"), net_weight=Decimal("1"))
    session.add_all([location, product])
    session.commit()
    company_id, site_id, product_id, location_id = company.id, site.id, product.id, location.id
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
            "site_id": str(site_id),
            "sale_no": "SO-NO-PRICE",
            "lines": [{"product_id": str(product_id),
                       "source_location_id": str(location_id)}],
        })
        assert response.status_code == 422
        assert "金價" in response.json()["detail"]
        check_session = TestSession()
        assert check_session.query(Sale).count() == 0
        check_session.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
