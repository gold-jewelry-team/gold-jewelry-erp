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


def test_customer_order_cannot_be_created_for_another_company_site():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="ORDER-SITE-OWNER", name="訂單所屬公司")
    other_company = Company(code="ORDER-SITE-OTHER", name="其他公司")
    db.add_all([company, other_company])
    db.flush()
    foreign_site = Site(
        company_id=other_company.id,
        code="FOREIGN",
        name="其他公司據點",
    )
    db.add(foreign_site)
    db.commit()
    company_id, foreign_site_id = company.id, foreign_site.id
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
                "site_id": str(foreign_site_id),
                "order_no": "CO-FOREIGN-SITE-001",
                "customer_name": "跨公司據點測試",
                "items": [{"product_name": "黃金墜子", "weight": 0.8}],
                "total_amount": "8000.00",
                "initial_deposit": "1000.00",
                "payment_method": "CASH",
            },
        )
        assert response.status_code == 422
        assert "指定據點不屬於目前公司" in response.json()["detail"]

        verify = TestSession()
        order_count = verify.scalar(
            select(func.count()).select_from(CustomerOrder)
        )
        payment_count = verify.scalar(
            select(func.count()).select_from(PaymentTransaction)
        )
        assert order_count == 0
        assert payment_count == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
