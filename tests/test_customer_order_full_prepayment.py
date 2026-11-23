from decimal import Decimal
from uuid import UUID

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


def test_customer_order_paid_in_full_at_creation_can_complete_after_delivery():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-PREPAID", name="客訂全額預付測試")
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
                "order_no": "CO-PREPAID-001",
                "customer_name": "全額預付客戶",
                "items": [{"product_name": "黃金項鍊", "weight": 3.5}],
                "total_amount": "50000.00",
                "initial_deposit": "50000.00",
                "payment_method": "CARD",
            },
        )
        assert created.status_code == 201, created.text
        order = created.json()
        assert order["status"] == "IN_PROGRESS"
        assert order["deposit_amount"] == "50000.00"
        assert order["balance_amount"] == "0.00"
        assert len(order["payments"]) == 1

        for next_status in ("ARRIVED", "READY", "COMPLETED"):
            changed = client.patch(
                f"/companies/{company_id}/customer-orders/{order['id']}/status",
                params={"status": next_status},
            )
            assert changed.status_code == 200, changed.text
            assert changed.json()["status"] == next_status
            assert changed.json()["balance_amount"] == "0.00"

        verify = TestSession()
        persisted = verify.scalar(
            select(CustomerOrder).where(CustomerOrder.id == UUID(order["id"]))
        )
        payment_count = verify.scalar(
            select(func.count()).select_from(PaymentTransaction).where(
                PaymentTransaction.customer_order_id == UUID(order["id"])
            )
        )
        payment_total = verify.scalar(
            select(func.sum(PaymentTransaction.amount)).where(
                PaymentTransaction.customer_order_id == UUID(order["id"])
            )
        )
        assert persisted.status == "COMPLETED"
        assert persisted.deposit_amount == Decimal("50000.00")
        assert payment_count == 1
        assert payment_total == Decimal("50000.00")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
