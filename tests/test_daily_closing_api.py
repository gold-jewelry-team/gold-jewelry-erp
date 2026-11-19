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
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.routers import daily_closing
from app.services.daily_closing import assert_business_day_open, create_daily_closing


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="DAY-CLOSE", name="每日結帳測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()

    # 2026-11-19 Taipei business day: 2026-11-18 16:00 UTC to 2026-11-19 16:00 UTC.
    cash_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="DC-CASH",
        status="COMPLETED", payment_method="CASH", currency_code="TWD",
        subtotal=Decimal("300"), card_fee=Decimal("0"),
        final_amount=Decimal("300"),
        completed_at=datetime(2026, 11, 19, 2, 0, tzinfo=timezone.utc),
    )
    card_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="DC-CARD",
        status="COMPLETED", payment_method="CARD", currency_code="TWD",
        subtotal=Decimal("500"), card_fee=Decimal("25"),
        final_amount=Decimal("525"),
        completed_at=datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc),
    )
    outside_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="DC-OUTSIDE",
        status="COMPLETED", payment_method="CASH", currency_code="TWD",
        subtotal=Decimal("900"), card_fee=Decimal("0"),
        final_amount=Decimal("900"),
        completed_at=datetime(2026, 11, 19, 16, 0, tzinfo=timezone.utc),
    )
    draft_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="DC-DRAFT",
        status="DRAFT", payment_method="CASH", currency_code="TWD",
        subtotal=Decimal("1000"), card_fee=Decimal("0"),
        final_amount=Decimal("1000"),
    )
    session.add_all([cash_sale, card_sale, outside_sale, draft_sale])
    session.flush()
    session.add(SaleReturn(
        company_id=company.id, site_id=site.id, sale_id=cash_sale.id,
        return_no="DC-RETURN", settlement_reversal_amount=Decimal("-100"),
        currency_code="TWD",
        created_at=datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc),
    ))
    session.commit()
    ids = (company.id, site.id, cash_sale.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[daily_closing.get_db] = override_db
    return engine, TestSession, ids


def test_daily_closing_snapshots_sales_returns_and_payment_methods():
    engine, TestSession, (company_id, site_id, _) = _context()
    try:
        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": "2026-11-19", "note": "每日結帳"},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["sales_count"] == 2
        assert result["returns_count"] == 1
        assert result["gross_sales_amount"] == "825.00"
        assert result["return_reversal_amount"] == "-100.00"
        assert result["net_sales_amount"] == "725.00"

        summaries = {item["payment_method"]: item for item in result["payment_summaries"]}
        assert summaries["CASH"]["sales_count"] == 1
        assert summaries["CASH"]["returns_count"] == 1
        assert summaries["CASH"]["net_sales_amount"] == "200.00"
        assert summaries["CARD"]["gross_sales_amount"] == "525.00"
        assert summaries["CARD"]["net_sales_amount"] == "525.00"

        duplicate = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": "2026-11-19"},
        )
        assert duplicate.status_code == 422

        listed = client.get(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            params={"from_date": "2026-11-19", "to_date": "2026-11-19"},
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        check = TestSession()
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_closed_business_day_rejects_new_sales_or_returns():
    engine, TestSession, (company_id, site_id, _) = _context()
    try:
        db = TestSession()
        create_daily_closing(
            db, company_id=company_id, site_id=site_id,
            business_date=date(2026, 11, 19),
        )
        db.commit()
        try:
            assert_business_day_open(
                db, site_id=site_id,
                at=datetime(2026, 11, 19, 5, 0, tzinfo=timezone.utc),
            )
            assert False, "closed day should reject new transaction"
        except ValueError as exc:
            assert "已結帳" in str(exc)
        db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_daily_closing_rejects_site_from_another_company():
    engine, TestSession, (company_id, site_id, _) = _context()
    try:
        db = TestSession()
        other = Company(code="OTHER-COMPANY", name="其他公司")
        db.add(other)
        db.flush()
        try:
            create_daily_closing(
                db, company_id=other.id, site_id=site_id,
                business_date=date(2026, 11, 19),
            )
            assert False, "cross-company site should be rejected"
        except ValueError as exc:
            assert "不屬於" in str(exc)
        db.rollback()
        db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
