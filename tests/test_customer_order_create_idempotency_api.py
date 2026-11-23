from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.site import Site
from app.routers import customer_orders


def _setup_customer_order_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    company = Company(code="ORDER-CREATE-IDEMP", name="客訂建立重送測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[customer_orders.get_db] = override_db
    return engine, test_session, TestClient(app), company_id, site_id


def _payload(site_id, key):
    return {
        "site_id": str(site_id),
        "order_no": "CO-CREATE-IDEMP-001",
        "customer_name": "建立重送客戶",
        "customer_phone": "0912345678",
        "expected_delivery_date": "2026-12-05T12:00:00+08:00",
        "items": [{
            "product_name": "客訂黃金戒指",
            "weight": 1.25,
            "weight_unit_code": "QIAN",
            "labor_fee": 800,
        }],
        "total_amount": "18000.00",
        "initial_deposit": "5000.00",
        "payment_method": "CASH",
        "note": "指定尺寸與刻字",
        "idempotency_key": str(key),
    }


def test_replaying_customer_order_create_returns_original_order_and_deposit_once():
    engine, test_session, client, company_id, site_id = _setup_customer_order_client()
    key = uuid4()
    payload = _payload(site_id, key)
    try:
        first = client.post(f"/companies/{company_id}/customer-orders", json=payload)
        replay = client.post(f"/companies/{company_id}/customer-orders", json=payload)

        assert first.status_code == 201, first.text
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["order_no"] == payload["order_no"]
        assert replay.json()["deposit_amount"] == "5000.00"
        assert replay.json()["balance_amount"] == "13000.00"
        assert len(replay.json()["payments"]) == 1

        verify = test_session()
        order_count = verify.scalar(
            select(func.count()).select_from(CustomerOrder).where(
                CustomerOrder.company_id == company_id
            )
        )
        payments = verify.scalars(select(PaymentTransaction).where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.customer_order_id == UUID(first.json()["id"]),
        )).all()
        assert order_count == 1
        assert len(payments) == 1
        assert payments[0].reference_no == f"CO-CREATE:{key}"
        assert payments[0].amount == Decimal("5000.00")
        assert payments[0].direction == "IN"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_customer_order_create_key_reused_with_changed_deposit_is_rejected():
    engine, test_session, client, company_id, site_id = _setup_customer_order_client()
    key = uuid4()
    payload = _payload(site_id, key)
    try:
        first = client.post(f"/companies/{company_id}/customer-orders", json=payload)
        changed_payload = {**payload, "initial_deposit": "6000.00"}
        conflict = client.post(
            f"/companies/{company_id}/customer-orders",
            json=changed_payload,
        )

        assert first.status_code == 201, first.text
        assert conflict.status_code == 409, conflict.text
        assert "不同的客訂內容" in conflict.json()["detail"]

        verify = test_session()
        order_count = verify.scalar(
            select(func.count()).select_from(CustomerOrder).where(
                CustomerOrder.company_id == company_id
            )
        )
        order = verify.scalar(select(CustomerOrder).where(
            CustomerOrder.company_id == company_id
        ))
        payment_count = verify.scalar(
            select(func.count()).select_from(PaymentTransaction).where(
                PaymentTransaction.company_id == company_id
            )
        )
        assert order_count == 1
        assert order.deposit_amount == Decimal("5000.00")
        assert payment_count == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
