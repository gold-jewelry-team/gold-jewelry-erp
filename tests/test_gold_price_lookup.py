from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.site import Site
from app.services.pricing.gold_prices import get_effective_gold_price


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_latest_effective_company_price_ignores_future_rows():
    engine, session = make_session()
    try:
        company = Company(code="C1", name="測試公司")
        session.add(company)
        session.flush()
        session.add_all([
            GoldPrice(
                company_id=company.id, price_type="SELL", price_value=Decimal("12000"),
                unit_code="TWD_PER_QIAN", effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            GoldPrice(
                company_id=company.id, price_type="SELL", price_value=Decimal("12500"),
                unit_code="TWD_PER_QIAN", effective_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            ),
        ])
        session.commit()

        result = get_effective_gold_price(
            session, company_id=company.id, price_type="SELL",
            at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert result is not None
        assert result.price_value == Decimal("12000.0000")
    finally:
        session.close()
        engine.dispose()


def test_site_price_overrides_company_price_and_falls_back_when_absent():
    engine, session = make_session()
    try:
        company = Company(code="C1", name="測試公司")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="S1", name="一店")
        session.add(site)
        session.flush()
        session.add_all([
            GoldPrice(
                company_id=company.id, site_id=None, price_type="BUY",
                price_value=Decimal("11000"), unit_code="TWD_PER_QIAN",
                effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            GoldPrice(
                company_id=company.id, site_id=site.id, price_type="BUY",
                price_value=Decimal("11100"), unit_code="TWD_PER_QIAN",
                effective_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        ])
        session.commit()

        site_result = get_effective_gold_price(
            session, company_id=company.id, site_id=site.id, price_type="BUY",
            at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        fallback_result = get_effective_gold_price(
            session, company_id=company.id, site_id=site.id, price_type="BUY",
            at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )
        assert site_result is not None and site_result.price_value == Decimal("11100.0000")
        assert fallback_result is not None and fallback_result.price_value == Decimal("11000.0000")
    finally:
        session.close()
        engine.dispose()
