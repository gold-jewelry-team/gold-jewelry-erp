from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.gold_price import GoldPrice
from app.models.inventory import InventoryMovement
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.sale import Sale
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import customer_orders, sales
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_customer_order_converts_to_one_sale_without_duplicate_cash_or_stock():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with TestSession() as db:
        company = Company(code="ORDER-SALE-LINK", name="客訂正式銷售整合測試")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        location = StorageLocation(
            site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
        )
        product = Product(
            company_id=company.id,
            product_code="ORDER-SALE-001",
            barcode="ORDER-SALE-BAR-001",
            name="客訂黃金戒指",
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
            reference_type="TEST",
        )
        company_id, site_id = company.id, site.id
        product_id, location_id = product.id, location.id
        db.commit()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    app.dependency_overrides[customer_orders.get_db] = override_db
    try:
        client = TestClient(app)
        order_create = client.post(
            f"/companies/{company_id}/customer-orders",
            json={
                "site_id": str(site_id),
                "order_no": "CO-SALE-001",
                "customer_name": "交貨測試客戶",
                "items": [{
                    "product_id": str(product_id),
                    "product_code": "ORDER-SALE-001",
                    "product_name": "客訂黃金戒指",
                    "weight": 1.0,
                    "weight_unit_code": "QIAN",
                    "labor_fee": 300,
                    "old_gold_weight": 0,
                    "trade_in_source": None,
                    "trade_in_ratio": None,
                    "estimated_line_amount": 12300,
                }],
                "total_amount": "12300.00",
                "initial_deposit": "2000.00",
                "payment_method": "CARD",
                "idempotency_key": str(uuid4()),
            },
        )
        assert order_create.status_code == 201, order_create.text
        order = order_create.json()
        order_id = UUID(order["id"])

        for status in ("ARRIVED", "READY"):
            response = client.patch(
                f"/companies/{company_id}/customer-orders/{order_id}/status",
                params={"status": status},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == status

        sale_payload = {
            "site_id": str(site_id),
            "customer_order_id": str(order_id),
            "sale_no": "SO-FROM-CO-001",
            "payment_method": "MIXED",
            "card_amount": "2000",
            "note": "客訂 CO-SALE-001 正式交貨",
            "lines": [{
                "product_id": str(product_id),
                "source_location_id": str(location_id),
            }],
        }
        created_sale = client.post(
            f"/companies/{company_id}/sales", json=sale_payload
        )
        assert created_sale.status_code == 201, created_sale.text
        sale = created_sale.json()
        sale_id = UUID(sale["id"])
        assert sale["customer_order_id"] == str(order_id)
        assert sale["subtotal"] == "12300.00"
        assert sale["card_amount"] == "2000.00"
        assert sale["card_fee"] == "100.00"
        assert sale["final_amount"] == "12400.00"
        assert sale["cash_amount"] == "10300.00"

        linked_order = client.get(
            f"/companies/{company_id}/customer-orders/{order_id}"
        )
        assert linked_order.status_code == 200, linked_order.text
        assert linked_order.json()["sale_id"] == str(sale_id)
        assert linked_order.json()["sale_no"] == "SO-FROM-CO-001"
        assert linked_order.json()["final_sale_amount"] == "12400.00"
        assert linked_order.json()["balance_amount"] == "10400.00"

        duplicate_sale = client.post(
            f"/companies/{company_id}/sales",
            json={**sale_payload, "sale_no": "SO-FROM-CO-DUP"},
        )
        assert duplicate_sale.status_code == 422
        assert "已建立正式銷售草稿" in duplicate_sale.json()["detail"]

        direct_complete = client.patch(
            f"/companies/{company_id}/customer-orders/{order_id}/status",
            params={"status": "COMPLETED"},
        )
        assert direct_complete.status_code == 409

        blocked = client.post(
            f"/companies/{company_id}/sales/{sale_id}/complete"
        )
        assert blocked.status_code == 422
        assert "尚有尾款" in blocked.json()["detail"]

        # Card principal already paid at order time is reused as part of this
        # sale's tender plan. The 5% fee is calculated once by the sale pricing
        # engine; only the remaining 100 card fee and 10,300 non-card balance
        # are collected as new customer-order payments.
        cash_balance = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/payments",
            json={
                "amount": "10300.00",
                "payment_method": "TRANSFER",
                "note": "交貨尾款轉帳",
                "idempotency_key": str(uuid4()),
            },
        )
        assert cash_balance.status_code == 200, cash_balance.text
        card_fee_balance = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/payments",
            json={
                "amount": "100.00",
                "payment_method": "CARD",
                "note": "交貨刷卡手續費",
                "idempotency_key": str(uuid4()),
            },
        )
        assert card_fee_balance.status_code == 200, card_fee_balance.text
        assert card_fee_balance.json()["deposit_amount"] == "12400.00"
        assert card_fee_balance.json()["balance_amount"] == "0.00"

        completed = client.post(
            f"/companies/{company_id}/sales/{sale_id}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        # Positive linked-sale receipts stay on the customer-order ledger.
        # Creating another sale payment would count the same cash twice.
        with TestSession() as db:
            from app.services.payments import record_sale_payment
            try:
                record_sale_payment(
                    db,
                    company_id=company_id,
                    sale_id=sale_id,
                    payment_method="CARD",
                    amount=Decimal("1"),
                )
                raise AssertionError("linked customer-order sale allowed a duplicate receipt")
            except ValueError as exc:
                assert "避免重複入帳" in str(exc)
            db.rollback()

        replay = client.post(
            f"/companies/{company_id}/sales/{sale_id}/complete"
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["completed_at"] == completed.json()["completed_at"]

        final_order = client.get(
            f"/companies/{company_id}/customer-orders/{order_id}"
        ).json()
        assert final_order["status"] == "COMPLETED"
        assert final_order["sale_id"] == str(sale_id)
        assert final_order["balance_amount"] == "0.00"

        with TestSession() as db:
            order_row = db.get(CustomerOrder, order_id)
            sale_row = db.get(Sale, sale_id)
            payments = list(db.scalars(
                select(PaymentTransaction)
                .where(PaymentTransaction.customer_order_id == order_id)
                .order_by(PaymentTransaction.paid_at, PaymentTransaction.id)
            ).all())
            sale_movements = list(db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.reference_type == "SALE_LINE"
                )
            ).all())
            assert order_row.status == "COMPLETED"
            assert order_row.deposit_amount == Decimal("12400.00")
            assert order_row.final_sale_amount == Decimal("12400.00")
            assert sale_row.customer_order_id == order_id
            assert len(payments) == 3
            assert sum(
                (item.amount if item.direction == "IN" else -item.amount for item in payments),
                Decimal("0"),
            ) == Decimal("12400.00")
            assert len(sale_movements) == 1
            assert sale_movements[0].movement_type == "SALE"
            assert get_stock_balance(
                db, product_id=product_id, location_id=location_id
            ) == Decimal("0")
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
