from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankAccount, BankTransaction
from app.models.cash_count import DailyCashCount
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.company import Company
from app.models.daily_closing import DailyClosing, DailyClosingPaymentSummary
from app.models.site import Site
from app.routers import operational_reports


BUSINESS_DATE = date(2026, 11, 19)
EVENT_TIME = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    company = Company(code="OP-RECON", name="結帳核對測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()

    closing = DailyClosing(
        company_id=company.id,
        site_id=site.id,
        business_date=BUSINESS_DATE,
        currency_code="TWD",
        sales_count=0,
        returns_count=0,
        gross_sales_amount=Decimal("0.00"),
        return_reversal_amount=Decimal("0.00"),
        net_sales_amount=Decimal("0.00"),
        collected_amount=Decimal("0.00"),
        refunded_amount=Decimal("0.00"),
        supplier_paid_amount=Decimal("0.00"),
        expenses_paid_amount=Decimal("0.00"),
        cash_drawer_in_amount=Decimal("0.00"),
        cash_drawer_out_amount=Decimal("110.00"),
        net_cash_flow=Decimal("0.00"),
    )
    db.add(closing)
    db.flush()
    db.add(DailyClosingPaymentSummary(
        closing_id=closing.id,
        payment_method="CASH",
        sales_count=0,
        returns_count=0,
        gross_sales_amount=Decimal("0.00"),
        return_reversal_amount=Decimal("0.00"),
        net_sales_amount=Decimal("0.00"),
        collected_amount=Decimal("0.00"),
        refunded_amount=Decimal("0.00"),
        supplier_paid_amount=Decimal("0.00"),
        expenses_paid_amount=Decimal("0.00"),
        cash_drawer_in_amount=Decimal("0.00"),
        cash_drawer_out_amount=Decimal("110.00"),
        net_cash_flow=Decimal("0.00"),
    ))
    bank_account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="7788",
        currency_code="TWD",
        opening_balance=Decimal("10000.00"),
        opening_balance_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_active=True,
    )
    db.add(bank_account)
    db.flush()
    bank_tx = BankTransaction(
        company_id=company.id,
        bank_account_id=bank_account.id,
        site_id=site.id,
        transaction_type="CASH_DEPOSIT",
        direction="IN",
        amount=Decimal("100.00"),
        currency_code="TWD",
        description="現金存入銀行",
        created_by_name="店員甲",
        occurred_at=EVENT_TIME,
    )
    db.add(bank_tx)
    db.flush()
    db.add_all([
        CashDrawerMovement(
            company_id=company.id,
            site_id=site.id,
            bank_transaction_id=bank_tx.id,
            movement_type="BANK_DEPOSIT",
            direction="OUT",
            amount=Decimal("100.00"),
            currency_code="TWD",
            description="存入銀行",
            created_by_name="店員甲",
            created_at=EVENT_TIME,
        ),
        CashDrawerMovement(
            company_id=company.id,
            site_id=site.id,
            movement_type="OTHER_OUT",
            direction="OUT",
            amount=Decimal("10.00"),
            currency_code="TWD",
            description="其他現金支出",
            created_by_name="店員甲",
            created_at=EVENT_TIME,
        ),
    ])
    db.add(DailyCashCount(
        company_id=company.id,
        site_id=site.id,
        closing_id=closing.id,
        currency_code="TWD",
        opening_cash_float=Decimal("1000.00"),
        expected_cash_amount=Decimal("890.00"),
        counted_cash_amount=Decimal("880.00"),
        cash_variance=Decimal("-10.00"),
        counted_by_name="盤點人甲",
    ))
    db.commit()
    ids = company.id, site.id

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[operational_reports.get_db] = override_db
    return engine, ids


def test_operational_report_cross_checks_daily_close_cash_count_and_bank_deposit():
    engine, (company_id, site_id) = _context()
    try:
        response = TestClient(app).get(
            f"/companies/{company_id}/sites/{site_id}/operational-report",
            params={"period_start": BUSINESS_DATE.isoformat(), "period_end": BUSINESS_DATE.isoformat()},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["daily_closings"]) == 1
        close = result["daily_closings"][0]
        assert close["status"] == "NEEDS_REVIEW"
        assert all(check["status"] == "PASS" for check in close["checks"])
        assert close["cash_count"]["expected_cash_amount"] == "890.00"
        assert close["cash_count"]["expected_from_operational_report"] == "890.00"
        assert close["cash_count"]["counted_cash_amount"] == "880.00"
        assert close["cash_count"]["cash_variance"] == "-10.00"
        assert result["daily_closing_summary"] == {
            "days_checked": 1, "errors": 0, "pending": 1,
        }
        assert result["bank_cash_movement_summary"] == {
            "transactions_checked": 1, "errors": 0,
        }
        assert result["bank_cash_movements"][0]["status"] == "PASS"
        assert result["bank_cash_movements"][0]["actual_drawer_movement"]["direction"] == "OUT"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_operational_report_flags_missing_daily_close_and_missing_bank_drawer_pair():
    engine, (company_id, site_id) = _context()
    try:
        from app.models.bank_account import BankTransaction
        from app.models.daily_closing import DailyClosing
        from app.models.cash_drawer_movement import CashDrawerMovement

        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = Session()
        # Remove the close/count and the linked drawer row while retaining the bank ledger.
        db.query(DailyCashCount).delete()
        db.query(DailyClosingPaymentSummary).delete()
        db.query(DailyClosing).delete()
        db.query(CashDrawerMovement).filter(CashDrawerMovement.bank_transaction_id.is_not(None)).delete()
        db.commit()
        db.close()

        response = TestClient(app).get(
            f"/companies/{company_id}/sites/{site_id}/operational-report",
            params={"period_start": BUSINESS_DATE.isoformat(), "period_end": BUSINESS_DATE.isoformat()},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["daily_closings"] == []
        assert result["daily_closing_summary"]["days_checked"] == 0
        assert result["bank_cash_movement_summary"]["errors"] == 1
        assert result["bank_cash_movements"][0]["status"] == "ERROR"
        assert result["bank_cash_movements"][0]["actual_drawer_movement"] is None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
