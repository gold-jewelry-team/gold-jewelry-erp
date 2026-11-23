from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.site import Site
from app.routers import customer_orders


def test_customer_order_deposit_above_total_is_rejected_without_creating_records():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-DEPOSIT-LIMIT", name="客訂訂金上限測試")
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
        response = client.post(
            f"/companies/{company_id}/customer-orders",
            json={
                "site_id": str(site_id),
                "order_no": "CO-DEPOSIT-LIMIT-001",
                "customer_name": "訂金超額測試",
                "items": [{"product_name": "黃金戒指", "weight": 1.0}],
                "total_amount": "10000.00",
                "initial_deposit": "10000.01",
                "payment_method": "CASH",
            },
        )
        assert response.status_code == 422
        assert "訂金不可超過訂購總額" in str(response.json())

        verify = TestSession()
        order_count = verify.scalar(
            select(func.count()).select_from(CustomerOrder).where(
                CustomerOrder.company_id == company_id
            )
        )
        payment_count = verify.scalar(
            select(func.count()).select_from(PaymentTransaction).where(
                PaymentTransaction.company_id == company_id
            )
        )
        assert order_count == 0
        assert payment_count == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
