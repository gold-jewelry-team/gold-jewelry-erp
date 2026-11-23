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
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import inventory, payments, sales, sales_returns
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_purchase_stock_transfer_sale_and_return_preserve_actual_location_and_ledger():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    company = Company(code="FLOW-TRANSFER-RETURN", name="調櫃銷售退貨整合測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    safe = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    display = StorageLocation(
        site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
    )
    product = Product(
        company_id=company.id,
        product_code="G00R-FLOW-001",
        barcode="471000000001",
        name="調櫃銷售退貨測試戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    db.add_all([safe, display, product])
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
    receipt = create_inventory_movement(
        db,
        company_id=company.id,
        site_id=site.id,
        product_id=product.id,
        movement_type="RECEIPT",
        quantity=Decimal("1"),
        to_location_id=safe.id,
        weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        reference_type="TEST_PURCHASE_RECEIPT",
    )
    db.commit()
    company_id, site_id, safe_id, display_id, product_id = (
        company.id, site.id, safe.id, display.id, product.id
    )
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    dependencies = (
        inventory.get_db,
        sales.get_db,
        payments.get_db,
        sales_returns.get_db,
    )
    app.dependency_overrides.clear()
    for dependency in dependencies:
        app.dependency_overrides[dependency] = override_db

    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"

        before = client.get(
            f"{base}/inventory/stock",
            params={"site_id": str(site_id), "location_id": str(safe_id)},
        )
        assert before.status_code == 200, before.text
        assert len(before.json()) == 1
        assert before.json()[0]["quantity"] == "1.000"

        transfer = client.post(f"{base}/inventory/transfers", json={
            "site_id": str(site_id),
            "product_id": str(product_id),
            "from_location_id": str(safe_id),
            "to_location_id": str(display_id),
            "quantity": "1",
            "weight": "1.0000",
            "weight_unit_code": "QIAN",
            "note": "上架展示櫃",
        })
        assert transfer.status_code == 201, transfer.text
        assert transfer.json()["movement_type"] == "TRANSFER"

        sale_response = client.post(f"{base}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-FLOW-TRANSFER-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(display_id),
            }],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        assert sale["lines"][0]["source_location_id"] == str(display_id)
        assert sale["final_amount"] == "12300.00"

        completed = client.post(f"{base}/sales/{sale['id']}/complete")
        assert completed.status_code == 200, completed.text
        collected = client.post(
            f"{base}/sales/{sale['id']}/payments",
            json={"payment_method": "CASH", "amount": "12300.00"},
        )
        assert collected.status_code == 201, collected.text
        assert collected.json()["direction"] == "IN"

        stock_after_sale = client.get(
            f"{base}/inventory/stock", params={"site_id": str(site_id)}
        )
        assert stock_after_sale.status_code == 200, stock_after_sale.text
        assert all(row["quantity"] == "0.000" for row in stock_after_sale.json())

        returned = client.post(
            f"{base}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-FLOW-TRANSFER-001",
                "sale_line_ids": [sale["lines"][0]["id"]],
                "reason": "客人退貨",
            },
        )
        assert returned.status_code == 201, returned.text
        assert returned.json()["settlement_reversal_amount"] == "-12300.00"
        refund = client.post(
            f"{base}/sales/returns/{returned.json()['id']}/payments",
            json={"payment_method": "CASH", "amount": "12300.00"},
        )
        assert refund.status_code == 201, refund.text
        assert refund.json()["direction"] == "OUT"

        verify = TestSession()
        assert get_stock_balance(
            verify, product_id=product_id, location_id=safe_id
        ) == Decimal("0")
        assert get_stock_balance(
            verify, product_id=product_id, location_id=display_id
        ) == Decimal("1")
        movements = list(verify.query(InventoryMovement).filter_by(
            product_id=product_id
        ).all())
        by_type = {row.movement_type: row for row in movements}
        assert set(by_type) == {"RECEIPT", "TRANSFER", "SALE", "RETURN"}
        assert by_type["RECEIPT"].id == receipt.id
        assert by_type["TRANSFER"].from_location_id == safe_id
        assert by_type["TRANSFER"].to_location_id == display_id
        assert by_type["SALE"].from_location_id == display_id
        assert by_type["RETURN"].to_location_id == display_id
        assert verify.query(Sale).filter_by(status="COMPLETED").count() == 1
        assert verify.query(SaleReturn).count() == 1
        payments_saved = verify.query(PaymentTransaction).order_by(
            PaymentTransaction.direction
        ).all()
        assert len(payments_saved) == 2
        assert {row.direction for row in payments_saved} == {"IN", "OUT"}
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
