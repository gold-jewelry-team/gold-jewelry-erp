from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.routers import payments


def test_sale_and_return_payment_endpoints_enforce_company_scope():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="PAYMENT-OWNER", name="收付款所屬公司")
    other = Company(code="PAYMENT-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    owner_site = Site(company_id=owner.id, code="MAIN", name="總店")
    other_site = Site(company_id=other.id, code="MAIN", name="總店")
    db.add_all([owner_site, other_site])
    db.flush()
    sale = Sale(
        company_id=owner.id,
        site_id=owner_site.id,
        sale_no="SO-PAYMENT-ISOLATION",
        status="COMPLETED",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("1000.00"),
        card_amount=Decimal("0.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("1000.00"),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(sale)
    db.flush()
    returned = SaleReturn(
        company_id=owner.id,
        site_id=owner_site.id,
        sale_id=sale.id,
        return_no="RT-PAYMENT-ISOLATION",
        settlement_reversal_amount=Decimal("-500.00"),
        currency_code="TWD",
    )
    db.add(returned)
    db.commit()
    owner_id, other_id = owner.id, other.id
    sale_id, return_id = sale.id, returned.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[payments.get_db] = override_db
    try:
        client = TestClient(app)
        base = f"/companies/{other_id}"
        sale_payments = client.get(f"{base}/sales/{sale_id}/payments")
        assert sale_payments.status_code == 200, sale_payments.text
        assert sale_payments.json() == []

        return_payments = client.get(
            f"{base}/sales/returns/{return_id}/payments"
        )
        assert return_payments.status_code == 200, return_payments.text
        assert return_payments.json() == []

        rejected_collection = client.post(
            f"{base}/sales/{sale_id}/payments",
            json={"payment_method": "CASH", "amount": "100.00"},
        )
        assert rejected_collection.status_code == 422
        assert "找不到指定銷售單" in rejected_collection.json()["detail"]

        rejected_refund = client.post(
            f"{base}/sales/returns/{return_id}/payments",
            json={"payment_method": "CASH", "amount": "100.00"},
        )
        assert rejected_refund.status_code == 422
        assert "找不到指定退貨單" in rejected_refund.json()["detail"]

        verify = TestSession()
        assert verify.query(PaymentTransaction).count() == 0
        persisted_sale = verify.get(Sale, sale_id)
        persisted_return = verify.get(SaleReturn, return_id)
        assert persisted_sale.company_id == owner_id
        assert persisted_sale.status == "COMPLETED"
        assert persisted_return.company_id == owner_id
        assert persisted_return.settlement_reversal_amount == Decimal("-500.00")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
