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
    product3 = Product(
        company_id=company.id,
        product_code="SALE-G-003",
        barcode="SALE-BAR-003",
        name="測試黃金手環",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    session.add_all([location, product, product2, product3])
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
    company_id, site_id, product_id, product2_id, product3_id, location_id = (
        company.id, site.id, product.id, product2.id, product3.id, location.id
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

        history = client.get(
            f"/companies/{company_id}/sales",
            params={"site_id": str(site_id), "q": "SALE-BAR-001", "status": "DRAFT"},
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert history.json()[0]["id"] == sale["id"]
        invalid_range = client.get(
            f"/companies/{company_id}/sales",
            params={"from_date": "2026-11-20", "to_date": "2026-11-19"},
        )
        assert invalid_range.status_code == 422

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

        # Point-of-sale tender matrix: card fee applies only to card principal,
        # while the remaining principal is cash and is never surcharged.
        three_items = [
            {"product_id": str(product_id), "source_location_id": str(location_id)},
            {"product_id": str(product2_id), "source_location_id": str(location_id)},
            {"product_id": str(product3_id), "source_location_id": str(location_id)},
        ]
        tender_cases = [
            # label, method, card principal, expected subtotal, card fee, cash principal, final
            ("3 items cash", "CASH", None, "36900.00", "0.00", "36900.00", "36900.00"),
            ("3 items card 1", "MIXED", "1", "36900.00", "0.00", "36899.00", "36900.00"),
            ("3 items card 11", "MIXED", "11", "36900.00", "1.00", "36889.00", "36901.00"),
            ("3 items card 10000", "MIXED", "10000", "36900.00", "500.00", "26900.00", "37400.00"),
            ("3 items half card", "MIXED", "18450", "36900.00", "923.00", "18450.00", "37823.00"),
            ("3 items almost all card", "MIXED", "36899", "36900.00", "1845.00", "1.00", "38745.00"),
            ("3 items full card", "CARD", None, "36900.00", "1845.00", "0.00", "38745.00"),
            ("2 items half card", "MIXED", "12300", "24600.00", "615.00", "12300.00", "25215.00"),
            ("1 item card 1000", "MIXED", "1000", "12300.00", "50.00", "11300.00", "12350.00"),
            ("1 item card 9999", "MIXED", "9999", "12300.00", "500.00", "2301.00", "12800.00"),
        ]
        for index, (label, method, card_principal, subtotal, fee, cash, final) in enumerate(tender_cases):
            line_count = 1 if label.startswith("1 item") else 2 if label.startswith("2 items") else 3
            payload = {
                "site_id": str(site_id),
                "sale_no": f"SO-TENDER-MATRIX-{index:02d}",
                "payment_method": method,
                "lines": three_items[:line_count],
            }
            if card_principal is not None:
                payload["card_amount"] = card_principal
            result = client.post(f"/companies/{company_id}/sales", json=payload)
            assert result.status_code == 201, f"{label}: {result.text}"
            data = result.json()
            assert data["subtotal"] == subtotal, label
            assert data["card_fee"] == fee, label
            assert data["cash_amount"] == cash, label
            assert data["final_amount"] == final, label
            assert sum(Decimal(line["final_amount"]) for line in data["lines"]) == Decimal(final), label

        # Invalid tenders must be rejected before a draft can be created.
        invalid_tenders = [
            ("over subtotal", "MIXED", "36901", three_items),
            ("fractional card principal", "MIXED", "1000.50", three_items),
            ("missing mixed card principal", "MIXED", None, three_items),
            ("transfer plus card principal", "TRANSFER", "100", three_items),
        ]
        for index, (label, method, card_principal, lines) in enumerate(invalid_tenders):
            payload = {
                "site_id": str(site_id),
                "sale_no": f"SO-TENDER-INVALID-{index:02d}",
                "payment_method": method,
                "lines": lines,
            }
            if card_principal is not None:
                payload["card_amount"] = card_principal
            rejected = client.post(f"/companies/{company_id}/sales", json=payload)
            assert rejected.status_code == 422, f"{label}: {rejected.text}"

        editable = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id), "sale_no": "SO-EDIT-DRAFT-001",
            "payment_method": "CASH",
            "lines": [{"product_id": str(product2_id), "source_location_id": str(location_id)}],
        })
        assert editable.status_code == 201, editable.text
        editable_id = editable.json()["id"]
        updated = client.patch(f"/companies/{company_id}/sales/{editable_id}", json={
            "site_id": str(site_id), "sale_no": "SO-EDIT-DRAFT-UPDATED",
            "payment_method": "MIXED", "card_amount": "1000",
            "note": "修改後草稿",
            "lines": [{"product_id": str(product3_id), "source_location_id": str(location_id),
                       "net_weight": "1.1000", "labor_fee": "350"}],
        })
        assert updated.status_code == 200, updated.text
        assert updated.json()["id"] == editable_id
        assert updated.json()["sale_no"] == "SO-EDIT-DRAFT-UPDATED"
        assert updated.json()["status"] == "DRAFT"
        assert updated.json()["payment_method"] == "MIXED"
        assert updated.json()["card_amount"] == "1000.00"
        assert updated.json()["lines"][0]["product_id"] == str(product3_id)
        assert updated.json()["lines"][0]["net_weight"] == "1.1000"
        assert updated.json()["note"] == "修改後草稿"

        completed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"
        locked_edit = client.patch(f"/companies/{company_id}/sales/{sale['id']}", json={
            "site_id": str(site_id), "sale_no": "SO-EDIT-COMPLETED",
            "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert locked_edit.status_code == 422

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
