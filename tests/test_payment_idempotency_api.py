from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
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
from app.services.daily_closing import create_daily_closing


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PAY-IDEMPOTENCY", name="收付款重送測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    now = datetime.now(timezone.utc)
    sale = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="SO-PAY-IDEMPOTENCY",
        status="COMPLETED",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("1000.00"),
        card_amount=Decimal("0.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("1000.00"),
        completed_at=now,
    )
    db.add(sale)
    db.flush()
    returned = SaleReturn(
        company_id=company.id,
        site_id=site.id,
        sale_id=sale.id,
        return_no="RT-PAY-IDEMPOTENCY",
        settlement_reversal_amount=Decimal("-500.00"),
        currency_code="TWD",
        created_at=now,
    )
    db.add(returned)
    db.commit()
    ids = (company.id, site.id, sale.id, returned.id)
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[payments.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    return engine, TestSession, ids


def test_sale_and_return_payment_retries_are_idempotent_and_payload_bound():
    engine, TestSession, (company_id, site_id, sale_id, return_id) = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        sale_key = str(uuid4())
        payload = {
            "payment_method": "CASH",
            "amount": "100.00",
            "reference_no": "CASH-RECEIPT-001",
            "note": "第一次收款",
            "idempotency_key": sale_key,
        }

        created = client.post(f"{base}/sales/{sale_id}/payments", json=payload)
        assert created.status_code == 201, created.text
        repeated = client.post(f"{base}/sales/{sale_id}/payments", json=payload)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["id"] == created.json()["id"]

        changed = {**payload, "amount": "120.00"}
        conflict = client.post(f"{base}/sales/{sale_id}/payments", json=changed)
        assert conflict.status_code == 409, conflict.text
        assert "識別碼" in conflict.json()["detail"]

        same_key_other_source = client.post(
            f"{base}/sales/returns/{return_id}/payments",
            json={
                "payment_method": "CASH",
                "amount": "100.00",
                "idempotency_key": sale_key,
            },
        )
        assert same_key_other_source.status_code == 409

        return_key = str(uuid4())
        return_payload = {
            "payment_method": "TRANSFER",
            "amount": "200.00",
            "reference_no": "REFUND-001",
            "note": "退貨退款",
            "idempotency_key": return_key,
        }
        refund = client.post(
            f"{base}/sales/returns/{return_id}/payments", json=return_payload
        )
        assert refund.status_code == 201, refund.text
        refund_retry = client.post(
            f"{base}/sales/returns/{return_id}/payments", json=return_payload
        )
        assert refund_retry.status_code == 200, refund_retry.text
        assert refund_retry.json()["id"] == refund.json()["id"]

        check = TestSession()
        assert check.query(PaymentTransaction).count() == 2
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_exact_payment_retry_still_succeeds_after_daily_close():
    engine, TestSession, (company_id, site_id, sale_id, return_id) = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        key = str(uuid4())
        payload = {
            "payment_method": "CASH",
            "amount": "100.00",
            "reference_no": "TIMEOUT-RETRY-001",
            "idempotency_key": key,
        }
        first = client.post(f"{base}/sales/{sale_id}/payments", json=payload)
        assert first.status_code == 201, first.text

        db = TestSession()
        business_date = datetime.now(ZoneInfo("Asia/Taipei")).date()
        create_daily_closing(
            db,
            company_id=company_id,
            site_id=site_id,
            business_date=business_date,
        )
        db.commit()
        db.close()

        retry = client.post(f"{base}/sales/{sale_id}/payments", json=payload)
        assert retry.status_code == 200, retry.text
        assert retry.json()["id"] == first.json()["id"]

        rejected_new_payment = client.post(
            f"{base}/sales/{sale_id}/payments",
            json={
                "payment_method": "CASH",
                "amount": "50.00",
                "idempotency_key": str(uuid4()),
            },
        )
        assert rejected_new_payment.status_code == 422
        assert "已結帳" in rejected_new_payment.json()["detail"]

        check = TestSession()
        assert check.query(PaymentTransaction).count() == 1
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_daily_closing_rejects_a_future_business_date():
    engine, TestSession, (company_id, site_id, _, _) = _context()
    try:
        db = TestSession()
        tomorrow = datetime.now(ZoneInfo("Asia/Taipei")).date() + timedelta(days=1)
        with pytest.raises(ValueError, match="不可提前結帳"):
            create_daily_closing(
                db,
                company_id=company_id,
                site_id=site_id,
                business_date=tomorrow,
            )
        db.rollback()
        assert db.query(DailyClosing).count() == 0
        db.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
