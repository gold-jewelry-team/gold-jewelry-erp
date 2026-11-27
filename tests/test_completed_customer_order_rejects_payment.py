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


def test_completed_customer_order_rejects_further_payment_without_ledger_change():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-CLOSED", name="已完成客訂單測試")
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
                "order_no": "CO-CLOSED-001",
                "customer_name": "測試客戶",
                "items": [{"product_name": "黃金手鍊", "weight": 2.0}],
                "total_amount": "2000.00",
                "initial_deposit": "1000.00",
                "payment_method": "CASH",
            },
        )
        assert created.status_code == 201, created.text
        order_id = created.json()["id"]

        for next_status in ("ARRIVED", "READY"):
            changed = client.patch(
                f"/companies/{company_id}/customer-orders/{order_id}/status",
                params={"status": next_status},
            )
            assert changed.status_code == 200, changed.text

        settled = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/payments",
            json={"amount": "1000.00", "payment_method": "TRANSFER"},
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["balance_amount"] == "0.00"

        with TestSession() as mark_completed:
            persisted_before = mark_completed.get(CustomerOrder, UUID(order_id))
            persisted_before.status = "COMPLETED"
            mark_completed.commit()

        late_payment = client.post(
            f"/companies/{company_id}/customer-orders/{order_id}/payments",
            json={"amount": "1.00", "payment_method": "CASH"},
        )
        assert late_payment.status_code == 422
        assert "已完成或已取消的訂單不可再收款" in late_payment.json()["detail"]

        verify = TestSession()
        persisted = verify.scalar(
            select(CustomerOrder).where(CustomerOrder.id == UUID(order_id))
        )
        payment_count = verify.scalar(
            select(func.count()).select_from(PaymentTransaction).where(
                PaymentTransaction.customer_order_id == UUID(order_id)
            )
        )
        payment_total = verify.scalar(
            select(func.sum(PaymentTransaction.amount)).where(
                PaymentTransaction.customer_order_id == UUID(order_id)
            )
        )
        assert persisted.status == "COMPLETED"
        assert persisted.deposit_amount == Decimal("2000.00")
        assert payment_count == 2
        assert payment_total == Decimal("2000.00")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
