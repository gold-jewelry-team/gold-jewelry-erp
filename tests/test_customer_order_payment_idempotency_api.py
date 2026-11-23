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


def test_customer_order_payment_retry_returns_existing_transaction_without_collecting_twice():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-PAY-IDEMP", name="客訂付款重送測試")
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
    try:
        client = TestClient(app)
        created = client.post(
            f"/companies/{company_id}/customer-orders",
            json={
                "site_id": str(site_id),
                "order_no": "CO-IDEMP-001",
                "customer_name": "付款重送客戶",
                "items": [{"product_name": "黃金戒指", "weight": 1.0}],
                "total_amount": "1000.00",
                "initial_deposit": "200.00",
                "payment_method": "CASH",
            },
        )
        assert created.status_code == 201, created.text
        order_id = created.json()["id"]
        key = str(uuid4())
        payload = {
            "amount": "800.00",
            "payment_method": "TRANSFER",
            "note": "交貨尾款",
            "idempotency_key": key,
        }
        url = f"/companies/{company_id}/customer-orders/{order_id}/payments"

        first = client.post(url, json=payload)
        replay = client.post(url, json=payload)

        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert first.json()["deposit_amount"] == "1000.00"
        assert replay.json()["deposit_amount"] == "1000.00"
        assert len(replay.json()["payments"]) == 2

        verify = TestSession()
        transactions = verify.scalars(select(PaymentTransaction).where(
            PaymentTransaction.customer_order_id == UUID(order_id)
        ).order_by(PaymentTransaction.paid_at)).all()
        assert len(transactions) == 2
        assert transactions[1].reference_no == f"CO-PAYMENT:{key}"
        assert sum((row.amount for row in transactions), Decimal("0")) == Decimal("1000.00")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_customer_order_payment_retry_key_cannot_be_reused_for_different_payment():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-PAY-KEY", name="客訂付款識別衝突測試")
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
    try:
        client = TestClient(app)
        created = client.post(
            f"/companies/{company_id}/customer-orders",
            json={
                "site_id": str(site_id),
                "order_no": "CO-IDEMP-002",
                "customer_name": "付款識別衝突客戶",
                "items": [{"product_name": "黃金手鍊", "weight": 1.0}],
                "total_amount": "1000.00",
                "initial_deposit": "200.00",
                "payment_method": "CASH",
            },
        )
        assert created.status_code == 201, created.text
        order_id = created.json()["id"]
        key = str(uuid4())
        url = f"/companies/{company_id}/customer-orders/{order_id}/payments"
        first = client.post(url, json={
            "amount": "300.00", "payment_method": "CASH",
            "note": "第一次付款", "idempotency_key": key,
        })
        conflict = client.post(url, json={
            "amount": "400.00", "payment_method": "CASH",
            "note": "不同金額", "idempotency_key": key,
        })

        assert first.status_code == 200, first.text
        assert conflict.status_code == 409, conflict.text
        assert "付款識別碼" in conflict.json()["detail"]

        verify = TestSession()
        order = verify.scalar(select(CustomerOrder).where(CustomerOrder.id == UUID(order_id)))
        count = verify.scalar(select(func.count()).select_from(PaymentTransaction).where(
            PaymentTransaction.customer_order_id == UUID(order_id)
        ))
        assert order.deposit_amount == Decimal("500.00")
        assert count == 2
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
