from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

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
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import daily_closing, payments, sales, sales_returns
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_sale_collection_return_refunds_and_daily_close_reconcile_end_to_end():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="SALE-RETURN-E2E", name="銷售退貨退款日結整合測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id,
        product_code="SALE-RETURN-E2E-001",
        barcode="SALE-RETURN-E2E-BAR-001",
        name="銷售退貨整合測試戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    db.add_all([location, product])
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
    company_id, site_id, location_id, product_id = (
        company.id, site.id, location.id, product.id
    )
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    dependencies = (
        sales.get_db,
        sales_returns.get_db,
        payments.get_db,
        daily_closing.get_db,
    )
    app.dependency_overrides.clear()
    for dependency in dependencies:
        app.dependency_overrides[dependency] = override_db
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        created = client.post(f"{base}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-RETURN-E2E-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        assert sale["subtotal"] == "12300.00"
        assert sale["final_amount"] == "12300.00"

        completed = client.post(f"{base}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        collected = client.post(
            f"{base}/sales/{sale['id']}/payments",
            json={"payment_method": "CASH", "amount": "12300.00"},
        )
        assert collected.status_code == 201, collected.text
        assert collected.json()["direction"] == "IN"

        returned = client.post(
            f"{base}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-E2E-001",
                "sale_line_ids": [sale["lines"][0]["id"]],
                "reason": "整合流程退貨",
            },
        )
        assert returned.status_code == 201, returned.text
        return_record = returned.json()
        assert return_record["settlement_reversal_amount"] == "-12300.00"

        refund_one = client.post(
            f"{base}/sales/returns/{return_record['id']}/payments",
            json={
                "payment_method": "TRANSFER",
                "amount": "5000.00",
                "reference_no": "REFUND-BANK-001",
            },
        )
        assert refund_one.status_code == 201, refund_one.text
        assert refund_one.json()["direction"] == "OUT"

        refund_two = client.post(
            f"{base}/sales/returns/{return_record['id']}/payments",
            json={"payment_method": "CASH", "amount": "7300.00"},
        )
        assert refund_two.status_code == 201, refund_two.text
        assert refund_two.json()["direction"] == "OUT"

        refund_history = client.get(
            f"{base}/sales/returns/{return_record['id']}/payments"
        )
        assert refund_history.status_code == 200, refund_history.text
        assert len(refund_history.json()) == 2
        assert sum(
            (Decimal(row["amount"]) for row in refund_history.json()),
            Decimal("0"),
        ) == Decimal("12300.00")

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"{base}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        snapshot = closing.json()
        assert snapshot["sales_count"] == 1
        assert snapshot["returns_count"] == 1
        assert snapshot["gross_sales_amount"] == "12300.00"
        assert snapshot["return_reversal_amount"] == "-12300.00"
        assert snapshot["net_sales_amount"] == "0.00"
        assert snapshot["collected_amount"] == "12300.00"
        assert snapshot["refunded_amount"] == "12300.00"
        assert snapshot["net_cash_flow"] == "0.00"
        summaries = {
            item["payment_method"]: item
            for item in snapshot["payment_summaries"]
        }
        assert summaries["CASH"]["gross_sales_amount"] == "12300.00"
        assert summaries["CASH"]["return_reversal_amount"] == "-12300.00"
        assert summaries["CASH"]["collected_amount"] == "12300.00"
        assert summaries["CASH"]["refunded_amount"] == "7300.00"
        assert summaries["TRANSFER"]["refunded_amount"] == "5000.00"

        verify = TestSession()
        assert verify.query(Sale).filter_by(status="COMPLETED").count() == 1
        assert verify.query(SaleReturn).count() == 1
        assert verify.query(PaymentTransaction).count() == 3
        assert verify.query(InventoryMovement).filter_by(
            reference_type="SALE_LINE"
        ).count() == 1
        assert verify.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).count() == 1
        assert get_stock_balance(
            verify, product_id=product_id, location_id=location_id
        ) == Decimal("1")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
