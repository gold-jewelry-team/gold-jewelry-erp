from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.daily_closing import DailyClosing
from app.models.site import Site
from app.services.cash_counts import create_cash_count, review_cash_count


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="CASH-REVIEW", name="現金覆核測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    closing = DailyClosing(
        company_id=company.id,
        site_id=site.id,
        business_date=date(2026, 11, 24),
    )
    session.add(closing)
    session.flush()
    return engine, TestSession, company.id, site.id, closing.id


def test_cash_count_variance_requires_nonblank_review_note():
    engine, TestSession, company_id, site_id, closing_id = _context()
    try:
        with TestSession() as session:
            count = create_cash_count(
                session,
                company_id=company_id,
                site_id=site_id,
                closing_id=closing_id,
                opening_cash_float=Decimal("500.00"),
                counted_cash_amount=Decimal("480.00"),
                counted_by_name="盤點人甲",
            )
            session.commit()
            count_id = count.id

        with TestSession() as session:
            try:
                review_cash_count(
                    session,
                    company_id=company_id,
                    site_id=site_id,
                    cash_count_id=count_id,
                    reviewed_by_name="覆核人乙",
                    review_note="   ",
                )
                assert False, "a variance must not be reviewed without an explanation"
            except ValueError as exc:
                assert "必須填寫覆核原因" in str(exc)

            reviewed = review_cash_count(
                session,
                company_id=company_id,
                site_id=site_id,
                cash_count_id=count_id,
                reviewed_by_name="覆核人乙",
                review_note="短少 20 元，已核對並登記差異。",
            )
            session.commit()
            assert reviewed.reviewed_by_name == "覆核人乙"
            assert reviewed.review_note == "短少 20 元，已核對並登記差異。"
    finally:
        engine.dispose()


def test_cash_count_without_variance_can_be_reviewed_without_note():
    engine, TestSession, company_id, site_id, closing_id = _context()
    try:
        with TestSession() as session:
            count = create_cash_count(
                session,
                company_id=company_id,
                site_id=site_id,
                closing_id=closing_id,
                opening_cash_float=Decimal("500.00"),
                counted_cash_amount=Decimal("500.00"),
                counted_by_name="盤點人甲",
            )
            session.commit()
            count_id = count.id

        with TestSession() as session:
            reviewed = review_cash_count(
                session,
                company_id=company_id,
                site_id=site_id,
                cash_count_id=count_id,
                reviewed_by_name="覆核人乙",
            )
            session.commit()
            assert reviewed.cash_variance == Decimal("0.00")
            assert reviewed.review_note is None
    finally:
        engine.dispose()
