from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
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


def test_customer_order_endpoints_are_scoped_to_owning_company():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    owner = Company(code="ORDER-OWNER", name="客訂單資料所屬公司")
    other = Company(code="ORDER-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    owner_site = Site(company_id=owner.id, code="OWNER", name="所屬據點")
    other_site = Site(company_id=other.id, code="OTHER", name="其他據點")
    db.add_all([owner_site, other_site])
    db.flush()

    order = CustomerOrder(
        company_id=owner.id,
        site_id=owner_site.id,
        order_no="CO-ISOLATION-001",
        status="IN_PROGRESS",
        customer_name="測試客戶",
        customer_phone=None,
        expected_delivery_date=None,
        items=[{"product_name": "黃金戒指", "weight": 1.0}],
        total_amount=Decimal("10000.00"),
        deposit_amount=Decimal("1000.00"),
        note=None,
    )
    db.add(order)
    db.commit()
    owner_id, other_id, order_id = owner.id, other.id, order.id
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

        listing = client.get(f"/companies/{other_id}/customer-orders")
        assert listing.status_code == 200, listing.text
        assert listing.json() == []

        detail = client.get(
            f"/companies/{other_id}/customer-orders/{order_id}"
        )
        assert detail.status_code == 404

        payment = client.post(
            f"/companies/{other_id}/customer-orders/{order_id}/payments",
            json={"amount": "100", "payment_method": "CASH"},
        )
        assert payment.status_code == 404

        status = client.patch(
            f"/companies/{other_id}/customer-orders/{order_id}/status",
            params={"status": "ARRIVED"},
        )
        assert status.status_code == 404

        verify = TestSession()
        persisted = verify.scalar(
            select(CustomerOrder).where(CustomerOrder.id == order_id)
        )
        payment_count = verify.scalar(
            select(func.count()).select_from(PaymentTransaction).where(
                PaymentTransaction.customer_order_id == order_id
            )
        )
        assert persisted.company_id == owner_id
        assert persisted.status == "IN_PROGRESS"
        assert persisted.deposit_amount == Decimal("1000.00")
        assert payment_count == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
