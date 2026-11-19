from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.site import Site
from app.services.pricing.gold_price_management import (
    create_gold_price,
    list_gold_prices,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_create_price_appends_history_and_list_orders_newest_first():
    engine, session = make_session()
    try:
        company = Company(code="C1", name="測試公司")
        session.add(company)
        session.flush()
        older = create_gold_price(
            session, company_id=company.id, price_type="SELL",
            price_value=Decimal("12000"), unit_code="TWD_PER_QIAN",
            effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        newer = create_gold_price(
            session, company_id=company.id, price_type="SELL",
            price_value=Decimal("12500"), unit_code="TWD_PER_QIAN",
            effective_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        session.commit()

        rows = list_gold_prices(session, company_id=company.id, price_type="SELL")
        assert [row.id for row in rows] == [newer.id, older.id]
        assert rows[0].price_value == Decimal("12500.0000")
        assert session.query(GoldPrice).count() == 2
    finally:
        session.close()
        engine.dispose()


def test_site_must_belong_to_selected_company():
    engine, session = make_session()
    try:
        company_a = Company(code="A", name="甲公司")
        company_b = Company(code="B", name="乙公司")
        session.add_all([company_a, company_b])
        session.flush()
        site_b = Site(company_id=company_b.id, code="S1", name="乙公司一店")
        session.add(site_b)
        session.flush()

        with pytest.raises(ValueError, match="不屬於該公司"):
            create_gold_price(
                session, company_id=company_a.id, site_id=site_b.id,
                price_type="BUY", price_value=Decimal("11000"),
                unit_code="TWD_PER_QIAN",
                effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_type": "MID"},
        {"price_value": Decimal("0")},
        {"unit_code": ""},
        {"currency_code": "NT"},
        {"source": "UNKNOWN"},
    ],
)
def test_invalid_price_values_are_rejected(overrides):
    engine, session = make_session()
    try:
        company = Company(code="C1", name="測試公司")
        session.add(company)
        session.flush()
        values = {
            "price_type": "BUY",
            "price_value": Decimal("11000"),
            "unit_code": "TWD_PER_QIAN",
            "currency_code": "TWD",
            "source": "MANUAL",
        }
        values.update(overrides)
        with pytest.raises(ValueError):
            create_gold_price(
                session, company_id=company.id,
                effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                **values,
            )
    finally:
        session.close()
        engine.dispose()
