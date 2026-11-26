from datetime import datetime
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
from app.models.site import Site
from app.models.payment_transaction import PaymentTransaction
from app.routers import cash_counts, customer_orders, daily_closing


def test_customer_order_deposit_ledger_and_status_flow():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-STORE", name="客訂單測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[customer_orders.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[cash_counts.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/customer-orders", json={
            "site_id": str(site_id),
            "order_no": "CO-TEST-001",
            "customer_name": "王小姐",
            "customer_phone": "0912000000",
            "items": [{"product_name": "客訂黃金戒指", "weight": 1.2, "weight_unit_code": "QIAN"}],
            "total_amount": "30000",
            "initial_deposit": "5000",
            "payment_method": "CASH",
        })
        assert created.status_code == 201, created.text
        order = created.json()
        assert order["status"] == "IN_PROGRESS"
        assert order["deposit_amount"] == "5000.00"
        assert order["balance_amount"] == "25000.00"
        assert len(order["payments"]) == 1

        arrived = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "ARRIVED"},
        )
        assert arrived.status_code == 200, arrived.text
        arrived_replay = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "ARRIVED"},
        )
        assert arrived_replay.status_code == 200, arrived_replay.text
        assert arrived_replay.json()["status"] == "ARRIVED"
        ready = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "READY"},
        )
        assert ready.status_code == 200, ready.text
        ready_replay = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "READY"},
        )
        assert ready_replay.status_code == 200, ready_replay.text
        assert ready_replay.json()["status"] == "READY"

        unpaid_completion = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "COMPLETED"},
        )
        assert unpaid_completion.status_code == 422
        assert "尚有尾款未收清" in unpaid_completion.json()["detail"]
        assert client.get(
            f"/companies/{company_id}/customer-orders/{order['id']}"
        ).json()["status"] == "READY"

        paid = client.post(f"/companies/{company_id}/customer-orders/{order['id']}/payments", json={
            "amount": "25000",
            "payment_method": "TRANSFER",
            "note": "交貨前尾款",
        })
        assert paid.status_code == 200, paid.text
        assert paid.json()["deposit_amount"] == "30000.00"
        assert paid.json()["balance_amount"] == "0.00"
        assert len(paid.json()["payments"]) == 2

        completed = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "COMPLETED"},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"
        completed_replay = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "COMPLETED"},
        )
        assert completed_replay.status_code == 200, completed_replay.text
        assert completed_replay.json()["status"] == "COMPLETED"

        ledger = TestSession()
        receipts = ledger.query(PaymentTransaction).filter(
            PaymentTransaction.customer_order_id == UUID(order["id"])
        ).all()
        assert len(receipts) == 2
        assert all(receipt.direction == "IN" for receipt in receipts)
        ledger.close()

        business_date = datetime.now(ZoneInfo("Asia/Taipei")).date()
        closing_response = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing_response.status_code == 201, closing_response.text
        closing = closing_response.json()
        assert closing["collected_amount"] == "30000.00"
        summaries = {
            row["payment_method"]: row for row in closing["payment_summaries"]
        }
        assert summaries["CASH"]["collected_amount"] == "5000.00"
        assert summaries["TRANSFER"]["collected_amount"] == "25000.00"

        cash_count = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings/"
            f"{closing['id']}/cash-count",
            json={
                "opening_cash_float": "1000.00",
                "counted_cash_amount": "6000.00",
                "counted_by_name": "盤點甲",
            },
        )
        assert cash_count.status_code == 201, cash_count.text
        assert cash_count.json()["expected_cash_amount"] == "6000.00"
        assert cash_count.json()["cash_variance"] == "0.00"

        duplicate_overpayment = client.post(f"/companies/{company_id}/customer-orders/{order['id']}/payments", json={
            "amount": "1", "payment_method": "CASH",
        })
        assert duplicate_overpayment.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_customer_order_basic_fields_can_be_edited_without_rewriting_deposit_or_items():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as db:
        company = Company(code="ORDER-EDIT", name="客訂單編輯測試")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        db.add(site)
        db.commit()
        company_id, site_id = company.id, site.id

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[customer_orders.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/customer-orders", json={
            "site_id": str(site_id),
            "order_no": "CO-EDIT-001",
            "customer_name": "王小姐",
            "customer_phone": "0912000000",
            "items": [{"product_name": "客訂黃金戒指", "weight": 1.2, "weight_unit_code": "QIAN"}],
            "total_amount": "30000",
            "initial_deposit": "5000",
            "payment_method": "CASH",
        })
        assert created.status_code == 201, created.text
        order = created.json()

        updated = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}",
            json={
                "order_no": "CO-EDIT-UPDATED",
                "customer_name": "王小姐（已更名）",
                "customer_phone": "0922000000",
                "expected_delivery_date": "2026-12-15T12:00:00+08:00",
                "note": "客戶改約交期",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["order_no"] == "CO-EDIT-UPDATED"
        assert updated.json()["customer_name"] == "王小姐（已更名）"
        assert updated.json()["customer_phone"] == "0922000000"
        assert updated.json()["total_amount"] == "30000.00"
        assert updated.json()["deposit_amount"] == "5000.00"
        assert updated.json()["items"] == order["items"]
        assert len(updated.json()["payments"]) == 1

        financial_edit = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}",
            json={"total_amount": "10000"},
        )
        assert financial_edit.status_code == 422

        arrived = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}/status",
            params={"status": "ARRIVED"},
        )
        assert arrived.status_code == 200, arrived.text
        locked = client.patch(
            f"/companies/{company_id}/customer-orders/{order['id']}",
            json={"customer_name": "到貨後不應修改"},
        )
        assert locked.status_code == 409
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_customer_order_refund_is_append_only_and_required_before_cancellation():
    from uuid import uuid4

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as db:
        company = Company(code="ORDER-REFUND", name="客訂退款測試公司")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        db.add(site)
        db.commit()
        company_id, site_id = company.id, site.id

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[customer_orders.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/customer-orders", json={
            "site_id": str(site_id), "order_no": "CO-REFUND-001",
            "customer_name": "退款測試客戶",
            "items": [{"product_name": "客訂商品"}],
            "total_amount": "10000", "initial_deposit": "3000",
            "payment_method": "CASH",
        })
        assert created.status_code == 201, created.text
        order_id = created.json()["id"]
        blocked = client.post(f"/companies/{company_id}/customer-orders/{order_id}/cancel")
        assert blocked.status_code == 409

        key = str(uuid4())
        refund_payload = {
            "amount": "3000.00", "payment_method": "TRANSFER",
            "note": "全額退還訂金", "idempotency_key": key,
        }
        refunded = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/refunds",
            json=refund_payload,
        )
        assert refunded.status_code == 200, refunded.text
        assert refunded.json()["deposit_amount"] == "0.00"
        assert len(refunded.json()["payments"]) == 2
        assert refunded.json()["payments"][-1]["direction"] == "OUT"

        retried = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/refunds",
            json=refund_payload,
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["deposit_amount"] == "0.00"
        assert len(retried.json()["payments"]) == 2

        cancelled = client.post(f"/companies/{company_id}/customer-orders/{order_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "CANCELLED"
        assert len(cancelled.json()["payments"]) == 2

        cancelled_replay = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/cancel"
        )
        assert cancelled_replay.status_code == 200, cancelled_replay.text
        assert cancelled_replay.json()["status"] == "CANCELLED"
        assert len(cancelled_replay.json()["payments"]) == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
