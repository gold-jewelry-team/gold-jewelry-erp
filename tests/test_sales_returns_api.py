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
from app.models.daily_closing import DailyClosing
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales, sales_returns, daily_closing
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
    product2 = Product(
        company_id=company.id,
        product_code=f"{code}-G-002",
        barcode=f"{code}-BAR-002",
        name="退貨測試黃金項鍊",
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
    for item in (product, product2):
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=item.id,
            movement_type="RECEIPT", quantity=Decimal("1"),
            to_location_id=location.id, weight=Decimal("1.0000"),
            weight_unit_code="QIAN", reference_type="TEST",
        )
    session.commit()
    ids = (company.id, site.id, product.id, product2.id, location.id)
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
    engine, TestSession, (company_id, site_id, product_id, _product2_id, location_id) = _return_test_context("RETURN-OK")
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-001",
            "payment_method": "CARD",
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
        assert record["settlement_reversal_amount"] == "-12915.00"
        assert record["lines"][0]["product_code_snapshot"] == "RETURN-OK-G-001"
        assert record["lines"][0]["settlement_reversal_amount"] == "-12915.00"

        history = client.get(f"/companies/{company_id}/sales/{sale['id']}/returns")
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert history.json()[0]["id"] == record["id"]
        assert history.json()[0]["lines"][0]["sale_line_id"] == line_id

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


def test_partial_return_reverses_original_multi_line_card_fee_allocation():
    engine, TestSession, (company_id, site_id, product_id, product2_id, location_id) = _return_test_context("RETURN-MULTI")
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-MULTI",
            "payment_method": "MIXED",
            "card_amount": "1010",
            "lines": [
                {"product_id": str(product_id), "source_location_id": str(location_id)},
                {"product_id": str(product2_id), "source_location_id": str(location_id)},
            ],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        assert [line["card_fee"] for line in sale["lines"]] == ["26.00", "25.00"]
        assert [line["final_amount"] for line in sale["lines"]] == ["12326.00", "12325.00"]

        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text

        # Return only line 2. Its original allocated fee (25) must be reversed;
        # the system must not recalculate a fresh 5% fee on the returned item.
        returned = client.post(f"/companies/{company_id}/sales/{sale['id']}/returns", json={
            "return_no": "RT-RETURN-MULTI-001",
            "sale_line_ids": [sale["lines"][1]["id"]],
        })
        assert returned.status_code == 201, returned.text
        record = returned.json()
        assert record["settlement_reversal_amount"] == "-12325.00"
        assert record["lines"][0]["settlement_reversal_amount"] == "-12325.00"

        check = TestSession()
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("0")
        assert get_stock_balance(check, product_id=product2_id, location_id=location_id) == Decimal("1")
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_draft_sale_cannot_be_returned():
    engine, TestSession, (company_id, site_id, product_id, _product2_id, location_id) = _return_test_context("RETURN-DRAFT")
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


def test_sale_return_is_blocked_after_daily_closing_without_restocking():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    engine, TestSession, (company_id, site_id, product_id, _product2_id, location_id) = _return_test_context("RETURN-CLOSED")
    app.dependency_overrides[daily_closing.get_db] = app.dependency_overrides[sales.get_db]
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-CLOSED",
            "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text

        returned = client.post(f"/companies/{company_id}/sales/{sale['id']}/returns", json={
            "return_no": "RT-RETURN-CLOSED",
            "sale_line_ids": [sale["lines"][0]["id"]],
            "reason": "結帳後測試退貨",
        })
        assert returned.status_code == 422
        assert "已結帳" in returned.json()["detail"]

        check = TestSession()
        assert check.query(SaleReturn).count() == 0
        assert check.query(DailyClosing).count() == 1
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("0")
        assert check.query(InventoryMovement).filter_by(reference_type="SALE_RETURN_LINE").count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_sale_can_be_returned_in_separate_partial_transactions():
    engine, TestSession, (company_id, site_id, product_id, product2_id, location_id) = _return_test_context("RETURN-SEQUENTIAL")
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-SEQUENTIAL",
            "payment_method": "MIXED",
            "card_amount": "1010",
            "lines": [
                {"product_id": str(product_id), "source_location_id": str(location_id)},
                {"product_id": str(product2_id), "source_location_id": str(location_id)},
            ],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text

        first_return = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-SEQUENTIAL-001",
                "sale_line_ids": [sale["lines"][0]["id"]],
                "reason": "第一次部分退貨",
            },
        )
        assert first_return.status_code == 201, first_return.text
        assert first_return.json()["settlement_reversal_amount"] == "-12326.00"

        after_first = TestSession()
        assert get_stock_balance(after_first, product_id=product_id, location_id=location_id) == Decimal("1")
        assert get_stock_balance(after_first, product_id=product2_id, location_id=location_id) == Decimal("0")
        after_first.close()

        second_return = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-SEQUENTIAL-002",
                "sale_line_ids": [sale["lines"][1]["id"]],
                "reason": "第二次部分退貨",
            },
        )
        assert second_return.status_code == 201, second_return.text
        assert second_return.json()["settlement_reversal_amount"] == "-12325.00"

        history = client.get(f"/companies/{company_id}/sales/{sale['id']}/returns")
        assert history.status_code == 200, history.text
        assert len(history.json()) == 2
        assert sum(
            (Decimal(record["settlement_reversal_amount"]) for record in history.json()),
            Decimal("0"),
        ) == Decimal("-24651.00")

        duplicate = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-SEQUENTIAL-003",
                "sale_line_ids": [sale["lines"][0]["id"]],
            },
        )
        assert duplicate.status_code == 422

        final_check = TestSession()
        assert final_check.query(SaleReturn).count() == 2
        assert final_check.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).count() == 2
        assert get_stock_balance(final_check, product_id=product_id, location_id=location_id) == Decimal("1")
        assert get_stock_balance(final_check, product_id=product2_id, location_id=location_id) == Decimal("1")
        final_check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_sale_return_exact_retry_is_idempotent_and_survives_daily_closing():
    from zoneinfo import ZoneInfo
    from app.services.daily_closing import create_daily_closing

    engine, TestSession, (company_id, site_id, product_id, _product2_id, location_id) = _return_test_context(
        "RETURN-IDEMPOTENT"
    )
    try:
        client = TestClient(app)
        sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-IDEMPOTENT",
            "payment_method": "CASH",
            "lines": [{"product_id": str(product_id), "source_location_id": str(location_id)}],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        completed = client.post(f"/companies/{company_id}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text

        payload = {
            "return_no": " RT-IDEMPOTENT-001 ",
            "sale_line_ids": [sale["lines"][0]["id"]],
            "reason": "顧客退貨",
            "note": "原始退貨備註",
        }
        first = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json=payload,
        )
        assert first.status_code == 201, first.text

        exact_retry = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={**payload, "return_no": "RT-IDEMPOTENT-001"},
        )
        assert exact_retry.status_code == 200, exact_retry.text
        assert exact_retry.json()["id"] == first.json()["id"]
        assert exact_retry.json()["settlement_reversal_amount"] == first.json()["settlement_reversal_amount"]

        conflicting_retry = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={**payload, "return_no": "RT-IDEMPOTENT-001", "reason": "不同退貨原因"},
        )
        assert conflicting_retry.status_code == 409, conflicting_retry.text

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing_session = TestSession()
        create_daily_closing(
            closing_session,
            company_id=company_id,
            site_id=site_id,
            business_date=business_date,
        )
        closing_session.commit()
        closing_session.close()

        # An exact retry after the close returns the original committed record;
        # it must not be rejected by the day lock or restock the item again.
        after_close_retry = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={**payload, "return_no": "RT-IDEMPOTENT-001"},
        )
        assert after_close_retry.status_code == 200, after_close_retry.text
        assert after_close_retry.json()["id"] == first.json()["id"]

        check = TestSession()
        assert check.query(SaleReturn).count() == 1
        assert check.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).count() == 1
        assert get_stock_balance(check, product_id=product_id, location_id=location_id) == Decimal("1")
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
