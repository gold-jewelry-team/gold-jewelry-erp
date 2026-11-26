from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.daily_closing import DailyClosing
from app.models.gold_price import GoldPrice
from app.models.inventory import InventoryMovement
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import customer_orders, daily_closing, payments, sales, sales_returns
from app.services.inventory import create_inventory_movement, get_stock_balance


def _context(code: str):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with TestSession() as db:
        company = Company(code=code, name="客訂成交與退貨結算邊界測試")
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
            product_code=f"{code}-001",
            barcode=f"{code}-BAR-001",
            name="客訂黃金戒指",
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
        ids = {
            "company_id": company.id,
            "site_id": site.id,
            "location_id": location.id,
            "product_id": product.id,
        }
        db.commit()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    dependencies = (
        customer_orders.get_db,
        daily_closing.get_db,
        payments.get_db,
        sales.get_db,
        sales_returns.get_db,
    )
    app.dependency_overrides.clear()
    for dependency in dependencies:
        app.dependency_overrides[dependency] = override_db
    return engine, TestSession, ids


def _create_order(client, ids, *, order_no, deposit, item, total="12300.00", items=None):
    response = client.post(
        f"/companies/{ids['company_id']}/customer-orders",
        json={
            "site_id": str(ids["site_id"]),
            "order_no": order_no,
            "customer_name": "邊界測試客戶",
            "items": items if items is not None else [item],
            "total_amount": total,
            "initial_deposit": deposit,
            "payment_method": "CASH",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    order = response.json()
    for status in ("ARRIVED", "READY"):
        changed = client.patch(
            f"/companies/{ids['company_id']}/customer-orders/{order['id']}/status",
            params={"status": status},
        )
        assert changed.status_code == 200, changed.text
    return order


def _business_date():
    return datetime.now(timezone.utc).astimezone(
        ZoneInfo("Asia/Taipei")
    ).date().isoformat()


def test_lower_delivery_price_refund_and_full_return_reconcile_customer_order_ledger():
    engine, TestSession, ids = _context("ORDER-LOWER-RETURN")
    try:
        client = TestClient(app)
        item = {
            "product_id": str(ids["product_id"]),
            "product_code": "ORDER-LOWER-RETURN-001",
            "product_name": "客訂黃金戒指",
            "weight": 1.0,
            "weight_unit_code": "QIAN",
            "labor_fee": 300,
            "old_gold_weight": 0,
            "trade_in_source": None,
            "trade_in_ratio": None,
            "estimated_line_amount": 12300,
        }
        order = _create_order(
            client, ids, order_no="CO-LOWER-RETURN-001",
            deposit="12000.00", item=item,
        )
        order_id = UUID(order["id"])
        base = f"/companies/{ids['company_id']}"

        sale_response = client.post(f"{base}/sales", json={
            "site_id": str(ids["site_id"]),
            "customer_order_id": str(order_id),
            "sale_no": "SO-LOWER-RETURN-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(ids["product_id"]),
                "source_location_id": str(ids["location_id"]),
                "net_weight": "0.8000",
            }],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        sale_id = UUID(sale["id"])
        assert sale["subtotal"] == "9900.00"
        assert sale["final_amount"] == "9900.00"

        linked = client.get(
            f"{base}/customer-orders/{order_id}"
        ).json()
        assert linked["final_sale_amount"] == "9900.00"
        assert linked["deposit_amount"] == "12000.00"
        assert linked["balance_amount"] == "-2100.00"

        # The excess must be refunded through a method that actually received
        # the original customer-order funds.
        wrong_method = client.post(
            f"{base}/customer-orders/{order_id}/refunds",
            json={
                "amount": "1.00",
                "payment_method": "TRANSFER",
                "idempotency_key": str(uuid4()),
            },
        )
        assert wrong_method.status_code == 422
        assert "可退超收餘額" in wrong_method.json()["detail"]

        refund_key = str(uuid4())
        refund_payload = {
            "amount": "2100.00",
            "payment_method": "CASH",
            "note": "交貨時依實際成交價退還超收",
            "idempotency_key": refund_key,
        }
        refund_url = f"{base}/customer-orders/{order_id}/refunds"
        refund = client.post(refund_url, json=refund_payload)
        refund_replay = client.post(refund_url, json=refund_payload)
        assert refund.status_code == 200, refund.text
        assert refund_replay.status_code == 200, refund_replay.text
        assert refund_replay.json()["deposit_amount"] == "9900.00"
        assert refund_replay.json()["balance_amount"] == "0.00"
        assert len(refund_replay.json()["payments"]) == 2

        over_refund = client.post(
            refund_url,
            json={
                "amount": "0.01",
                "payment_method": "CASH",
                "idempotency_key": str(uuid4()),
            },
        )
        assert over_refund.status_code == 422

        completed = client.post(f"{base}/sales/{sale_id}/complete")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"
        assert get_stock_balance(
            TestSession(), product_id=ids["product_id"],
            location_id=ids["location_id"],
        ) == Decimal("0")

        return_url = f"{base}/sales/{sale_id}/returns"
        return_payload = {
            "return_no": "RT-LOWER-RETURN-001",
            "sale_line_ids": [sale["lines"][0]["id"]],
            "reason": "完整退貨",
        }
        returned = client.post(return_url, json=return_payload)
        returned_replay = client.post(return_url, json=return_payload)
        assert returned.status_code == 201, returned.text
        assert returned_replay.status_code == 200, returned_replay.text
        return_record = returned.json()
        return_id = UUID(return_record["id"])
        assert return_record["settlement_reversal_amount"] == "-9900.00"
        assert get_stock_balance(
            TestSession(), product_id=ids["product_id"],
            location_id=ids["location_id"],
        ) == Decimal("1")

        return_payment_key = str(uuid4())
        return_payment_payload = {
            "payment_method": "TRANSFER",
            "amount": "9900.00",
            "note": "客訂商品完整退貨退款",
            "idempotency_key": return_payment_key,
        }
        return_payment_url = f"{base}/sales/returns/{return_id}/payments"
        return_payment = client.post(return_payment_url, json=return_payment_payload)
        return_payment_replay = client.post(return_payment_url, json=return_payment_payload)
        assert return_payment.status_code == 201, return_payment.text
        assert return_payment.json()["direction"] == "OUT"
        assert return_payment_replay.status_code == 200, return_payment_replay.text

        order_after_return = client.get(
            f"{base}/customer-orders/{order_id}"
        )
        assert order_after_return.status_code == 200, order_after_return.text
        sale_projection = order_after_return.json()["sale"]
        assert sale_projection["sale_no"] == "SO-LOWER-RETURN-001"
        assert sale_projection["return_status"] == "FULL"
        assert sale_projection["return_count"] == 1
        assert sale_projection["line_count"] == 1
        assert sale_projection["returned_line_count"] == 1
        assert sale_projection["return_reversal_amount"] == "-9900.00"
        return_projection = sale_projection["returns"][0]
        assert return_projection["settlement_direction"] == "OUT"
        assert return_projection["settled_amount"] == "9900.00"
        assert return_projection["outstanding_amount"] == "0.00"
        assert return_projection["settlement_status"] == "SETTLED"
        assert return_projection["payments"][0]["direction"] == "OUT"

        with TestSession() as db:
            order_payments = list(db.scalars(select(PaymentTransaction).where(
                PaymentTransaction.customer_order_id == order_id
            )).all())
            return_payments = list(db.scalars(select(PaymentTransaction).where(
                PaymentTransaction.sale_return_id == return_id
            )).all())
            sale_payments = list(db.scalars(select(PaymentTransaction).where(
                PaymentTransaction.sale_id == sale_id
            )).all())
            assert len(order_payments) == 2
            assert len(return_payments) == 1
            assert sale_payments == []
            assert sum(
                (p.amount if p.direction == "IN" else -p.amount for p in order_payments),
                Decimal("0"),
            ) == Decimal("9900.00")
            assert return_payments[0].direction == "OUT"
            assert return_payments[0].amount == Decimal("9900.00")

        closing_response = client.post(
            f"{base}/sites/{ids['site_id']}/daily-closings",
            json={"business_date": _business_date()},
        )
        assert closing_response.status_code == 201, closing_response.text
        closing = closing_response.json()
        assert closing["sales_count"] == 1
        assert closing["returns_count"] == 1
        assert closing["gross_sales_amount"] == "9900.00"
        assert closing["return_reversal_amount"] == "-9900.00"
        assert closing["net_sales_amount"] == "0.00"
        assert closing["collected_amount"] == "12000.00"
        assert closing["refunded_amount"] == "12000.00"
        assert closing["net_cash_flow"] == "0.00"
        summaries = {row["payment_method"]: row for row in closing["payment_summaries"]}
        assert summaries["CASH"]["gross_sales_amount"] == "9900.00"
        assert summaries["CASH"]["return_reversal_amount"] == "-9900.00"
        assert summaries["CASH"]["collected_amount"] == "12000.00"
        assert summaries["CASH"]["refunded_amount"] == "2100.00"
        assert summaries["TRANSFER"]["refunded_amount"] == "9900.00"

        with TestSession() as db:
            persisted_order = db.get(CustomerOrder, order_id)
            persisted_sale = db.get(Sale, sale_id)
            persisted_return = db.get(SaleReturn, return_id)
            assert persisted_order.status == "COMPLETED"
            assert persisted_order.deposit_amount == Decimal("9900.00")
            assert persisted_sale.customer_order_id == order_id
            assert persisted_return.settlement_reversal_amount == Decimal("-9900.00")
            assert db.query(InventoryMovement).filter_by(
                reference_type="SALE_LINE"
            ).count() == 1
            assert db.query(InventoryMovement).filter_by(
                reference_type="SALE_RETURN_LINE"
            ).count() == 1
            assert db.query(DailyClosing).count() == 1
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_negative_trade_in_sale_refunds_order_deposit_then_pays_store_obligation():
    engine, TestSession, ids = _context("ORDER-NEGATIVE-TRADEIN")
    try:
        client = TestClient(app)
        item = {
            "product_id": str(ids["product_id"]),
            "product_code": "ORDER-NEGATIVE-TRADEIN-001",
            "product_name": "客訂黃金戒指",
            "weight": 1.0,
            "weight_unit_code": "QIAN",
            "labor_fee": 300,
            "old_gold_weight": 2.0,
            "trade_in_source": "LOCAL",
            "trade_in_ratio": 1.0,
            "estimated_line_amount": 0,
        }
        order = _create_order(
            client, ids, order_no="CO-NEGATIVE-TRADEIN-001",
            deposit="1000.00", item=item,
        )
        order_id = UUID(order["id"])
        base = f"/companies/{ids['company_id']}"

        sale_response = client.post(f"{base}/sales", json={
            "site_id": str(ids["site_id"]),
            "customer_order_id": str(order_id),
            "sale_no": "SO-NEGATIVE-TRADEIN-001",
            "payment_method": "CASH",
            "lines": [{
                "product_id": str(ids["product_id"]),
                "source_location_id": str(ids["location_id"]),
                "net_weight": "1.0000",
                "old_gold_weight": "2.0000",
                "trade_in_source": "LOCAL",
                "trade_in_ratio": "1.000000",
            }],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        sale_id = UUID(sale["id"])
        assert sale["subtotal"] == "-10700.00"
        assert sale["card_fee"] == "0.00"
        assert sale["final_amount"] == "-10700.00"
        assert sale["cash_amount"] == "0.00"

        premature = client.post(f"{base}/sales/{sale_id}/complete")
        assert premature.status_code == 422
        assert "先退還客訂目前淨收款" in premature.json()["detail"]

        refund_key = str(uuid4())
        refund_payload = {
            "amount": "1000.00",
            "payment_method": "CASH",
            "note": "負數成交先退還原客訂訂金",
            "idempotency_key": refund_key,
        }
        refund_url = f"{base}/customer-orders/{order_id}/refunds"
        refund = client.post(refund_url, json=refund_payload)
        refund_replay = client.post(refund_url, json=refund_payload)
        assert refund.status_code == 200, refund.text
        assert refund_replay.status_code == 200, refund_replay.text
        assert refund_replay.json()["deposit_amount"] == "0.00"
        assert refund_replay.json()["balance_amount"] == "-10700.00"

        completed = client.post(f"{base}/sales/{sale_id}/complete")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        payout_key = str(uuid4())
        payout_payload = {
            "payment_method": "TRANSFER",
            "amount": "10700.00",
            "reference_no": "STORE-TRADEIN-REFUND-001",
            "note": "舊金超額折抵，店家支付差額",
            "idempotency_key": payout_key,
        }
        payout_url = f"{base}/sales/{sale_id}/payments"
        payout = client.post(payout_url, json=payout_payload)
        payout_replay = client.post(payout_url, json=payout_payload)
        assert payout.status_code == 201, payout.text
        assert payout.json()["direction"] == "OUT"
        assert payout_replay.status_code == 200, payout_replay.text
        assert payout_replay.json()["amount"] == "10700.00"

        with TestSession() as db:
            order_payments = list(db.scalars(select(PaymentTransaction).where(
                PaymentTransaction.customer_order_id == order_id
            )).all())
            sale_payments = list(db.scalars(select(PaymentTransaction).where(
                PaymentTransaction.sale_id == sale_id
            )).all())
            assert len(order_payments) == 2
            assert [p.direction for p in order_payments].count("IN") == 1
            assert [p.direction for p in order_payments].count("OUT") == 1
            assert len(sale_payments) == 1
            assert sale_payments[0].direction == "OUT"
            assert sale_payments[0].amount == Decimal("10700.00")
            assert db.get(CustomerOrder, order_id).deposit_amount == Decimal("0.00")
            assert get_stock_balance(
                db, product_id=ids["product_id"], location_id=ids["location_id"]
            ) == Decimal("0")

        closing_response = client.post(
            f"{base}/sites/{ids['site_id']}/daily-closings",
            json={"business_date": _business_date()},
        )
        assert closing_response.status_code == 201, closing_response.text
        closing = closing_response.json()
        assert closing["sales_count"] == 1
        assert closing["gross_sales_amount"] == "-10700.00"
        assert closing["net_sales_amount"] == "-10700.00"
        assert closing["collected_amount"] == "1000.00"
        assert closing["refunded_amount"] == "11700.00"
        assert closing["net_cash_flow"] == "-10700.00"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_customer_order_projection_shows_partial_return_and_unsettled_refund():
    engine, TestSession, ids = _context("ORDER-PARTIAL-RETURN")
    try:
        with TestSession() as db:
            create_inventory_movement(
                db,
                company_id=ids["company_id"],
                site_id=ids["site_id"],
                product_id=ids["product_id"],
                movement_type="RECEIPT",
                quantity=Decimal("1"),
                to_location_id=ids["location_id"],
                weight=Decimal("1.0000"),
                weight_unit_code="QIAN",
                reference_type="TEST-RECEIPT-SECOND",
            )
            db.commit()

        client = TestClient(app)
        item = {
            "product_id": str(ids["product_id"]),
            "product_code": "ORDER-PARTIAL-RETURN-001",
            "product_name": "客訂黃金戒指",
            "weight": 1.0,
            "weight_unit_code": "QIAN",
            "labor_fee": 300,
            "old_gold_weight": 0,
            "trade_in_source": None,
            "trade_in_ratio": None,
            "estimated_line_amount": 12300,
        }
        order = _create_order(
            client, ids,
            order_no="CO-PARTIAL-RETURN-001",
            deposit="24600.00",
            item=item,
            items=[item, item],
            total="24600.00",
        )
        order_id = UUID(order["id"])
        base = f"/companies/{ids['company_id']}"
        sale_response = client.post(f"{base}/sales", json={
            "site_id": str(ids["site_id"]),
            "customer_order_id": str(order_id),
            "sale_no": "SO-PARTIAL-RETURN-001",
            "payment_method": "CASH",
            "lines": [
                {"product_id": str(ids["product_id"]), "source_location_id": str(ids["location_id"])},
                {"product_id": str(ids["product_id"]), "source_location_id": str(ids["location_id"])},
            ],
        })
        assert sale_response.status_code == 201, sale_response.text
        sale = sale_response.json()
        sale_id = UUID(sale["id"])
        assert sale["final_amount"] == "24600.00"

        completed = client.post(f"{base}/sales/{sale_id}/complete")
        assert completed.status_code == 200, completed.text

        returned = client.post(
            f"{base}/sales/{sale_id}/returns",
            json={
                "return_no": "RT-PARTIAL-RETURN-001",
                "sale_line_ids": [sale["lines"][0]["id"]],
                "reason": "只退其中一件",
            },
        )
        assert returned.status_code == 201, returned.text

        projection = client.get(
            f"{base}/customer-orders/{order_id}"
        )
        assert projection.status_code == 200, projection.text
        order_json = projection.json()
        assert order_json["status"] == "COMPLETED"
        sale_json = order_json["sale"]
        assert sale_json["return_status"] == "PARTIAL"
        assert sale_json["line_count"] == 2
        assert sale_json["returned_line_count"] == 1
        assert sale_json["returns"][0]["settlement_status"] == "UNPAID"
        assert sale_json["returns"][0]["settled_amount"] == "0.00"
        assert sale_json["returns"][0]["outstanding_amount"] == "12300.00"

        return_id = returned.json()["id"]
        paid = client.post(
            f"{base}/sales/returns/{return_id}/payments",
            json={
                "payment_method": "TRANSFER",
                "amount": "5000.00",
                "note": "先退部分款項",
            },
        )
        assert paid.status_code == 201, paid.text
        after_partial_refund = client.get(
            f"{base}/customer-orders/{order_id}"
        ).json()["sale"]["returns"][0]
        assert after_partial_refund["settlement_status"] == "PARTIAL"
        assert after_partial_refund["settled_amount"] == "5000.00"
        assert after_partial_refund["outstanding_amount"] == "7300.00"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
