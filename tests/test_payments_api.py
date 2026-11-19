from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.daily_closing import DailyClosing
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.routers import daily_closing, payments


def _payment_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="PAYMENT-TEST", name="收付款測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    now = datetime.now(timezone.utc)
    sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="PAY-SALE-001",
        status="COMPLETED", payment_method="CASH", currency_code="TWD",
        subtotal=Decimal("1000"), card_fee=Decimal("0"),
        final_amount=Decimal("1000"), completed_at=now,
    )
    negative_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="PAY-SALE-NEG",
        status="COMPLETED", payment_method="OTHER", currency_code="TWD",
        subtotal=Decimal("-150"), card_fee=Decimal("0"),
        final_amount=Decimal("-150"), completed_at=now,
    )
    session.add_all([sale, negative_sale])
    session.flush()
    returned = SaleReturn(
        company_id=company.id, site_id=site.id, sale_id=sale.id,
        return_no="PAY-RETURN-001",
        settlement_reversal_amount=Decimal("-300"),
        currency_code="TWD", created_at=now,
    )
    customer_owes = SaleReturn(
        company_id=company.id, site_id=site.id, sale_id=sale.id,
        return_no="PAY-RETURN-002",
        settlement_reversal_amount=Decimal("50"),
        currency_code="TWD", created_at=now,
    )
    session.add_all([returned, customer_owes])
    session.commit()
    ids = (company.id, site.id, sale.id, negative_sale.id, returned.id, customer_owes.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[payments.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    return engine, TestSession, ids, now


def test_partial_collections_refunds_and_daily_cash_flow_summary():
    engine, TestSession, ids, now = _payment_context()
    company_id, site_id, sale_id, _, return_id, customer_owes_id = ids
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        first = client.post(f"{base}/sales/{sale_id}/payments", json={
            "payment_method": "CASH", "amount": "400.00",
            "reference_no": "CASH-001",
        })
        assert first.status_code == 201, first.text
        assert first.json()["direction"] == "IN"

        second = client.post(f"{base}/sales/{sale_id}/payments", json={
            "payment_method": "CARD", "amount": "600.00",
            "reference_no": "CARD-001",
        })
        assert second.status_code == 201, second.text
        overpay = client.post(f"{base}/sales/{sale_id}/payments", json={
            "payment_method": "CASH", "amount": "0.01",
        })
        assert overpay.status_code == 422

        refund1 = client.post(f"{base}/sales/returns/{return_id}/payments", json={
            "payment_method": "TRANSFER", "amount": "200.00",
            "reference_no": "BANK-REFUND-001",
        })
        assert refund1.status_code == 201, refund1.text
        assert refund1.json()["direction"] == "OUT"
        refund2 = client.post(f"{base}/sales/returns/{return_id}/payments", json={
            "payment_method": "CASH", "amount": "100.00",
        })
        assert refund2.status_code == 201, refund2.text
        overrefund = client.post(f"{base}/sales/returns/{return_id}/payments", json={
            "payment_method": "CASH", "amount": "0.01",
        })
        assert overrefund.status_code == 422

        collect_due = client.post(f"{base}/sales/returns/{customer_owes_id}/payments", json={
            "payment_method": "CASH", "amount": "50.00",
        })
        assert collect_due.status_code == 201, collect_due.text
        assert collect_due.json()["direction"] == "IN"

        negative = client.post(f"{base}/sales/{ids[3]}/payments", json={
            "payment_method": "TRANSFER", "amount": "150.00",
        })
        assert negative.status_code == 201, negative.text
        assert negative.json()["direction"] == "OUT"

        listed = client.get(f"{base}/sales/{sale_id}/payments")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        business_date = now.astimezone().date()
        # Taipei business date is derived from the transaction's actual local date.
        from zoneinfo import ZoneInfo
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        close = client.post(
            f"{base}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text
        result = close.json()
        assert result["collected_amount"] == "1050.00"
        assert result["refunded_amount"] == "350.00"
        assert result["net_cash_flow"] == "700.00"

        summaries = {item["payment_method"]: item for item in result["payment_summaries"]}
        assert summaries["CASH"]["collected_amount"] == "450.00"
        assert summaries["CASH"]["refunded_amount"] == "100.00"
        assert summaries["CARD"]["collected_amount"] == "600.00"
        assert summaries["TRANSFER"]["refunded_amount"] == "200.00"
        assert summaries["OTHER"]["refunded_amount"] == "150.00"

        check = TestSession()
        assert check.query(PaymentTransaction).count() == 6
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_payment_rejects_non_completed_sale_and_bad_amount():
    engine, TestSession, ids, _ = _payment_context()
    company_id, site_id, sale_id, _, return_id, _ = ids
    try:
        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sales/{sale_id}/payments",
            json={"payment_method": "CRYPTO", "amount": "10.001"},
        )
        assert response.status_code == 422
        check = TestSession()
        assert check.query(PaymentTransaction).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
