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
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierPayment
from app.models.operating_expense import OperatingExpense
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.payment_transaction import PaymentTransaction
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.site import Site
from app.routers import daily_closing, cash_counts
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
    mixed_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="DC-MIXED",
        status="COMPLETED", payment_method="MIXED", currency_code="TWD",
        subtotal=Decimal("1000"), card_amount=Decimal("500"),
        card_fee=Decimal("25"), final_amount=Decimal("1025"),
        completed_at=datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc),
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
    session.add_all([cash_sale, card_sale, mixed_sale, outside_sale, draft_sale])
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
    app.dependency_overrides[cash_counts.get_db] = override_db
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
        assert result["sales_count"] == 3
        assert result["returns_count"] == 1
        assert result["gross_sales_amount"] == "1850.00"
        assert result["return_reversal_amount"] == "-100.00"
        assert result["net_sales_amount"] == "1750.00"

        summaries = {item["payment_method"]: item for item in result["payment_summaries"]}
        assert summaries["CASH"]["sales_count"] == 1
        assert summaries["CASH"]["returns_count"] == 1
        assert summaries["CASH"]["net_sales_amount"] == "200.00"
        assert summaries["CARD"]["gross_sales_amount"] == "525.00"
        assert summaries["CARD"]["net_sales_amount"] == "525.00"
        assert summaries["MIXED"]["sales_count"] == 1
        assert summaries["MIXED"]["gross_sales_amount"] == "1025.00"
        assert summaries["MIXED"]["net_sales_amount"] == "1025.00"

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



def test_daily_closing_separates_return_obligation_from_actual_refund_and_drawer_deposit():
    engine, TestSession, (company_id, site_id, cash_sale_id) = _context()
    try:
        db = TestSession()
        returned = db.query(SaleReturn).filter_by(return_no="DC-RETURN").one()
        return_id = returned.id
        paid_at = datetime(2026, 11, 19, 5, 0, tzinfo=timezone.utc)
        db.add_all([
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_id=cash_sale_id,
                direction="IN", payment_method="CASH", amount=Decimal("300.00"),
                currency_code="TWD", paid_at=paid_at, note="原銷售實收",
            ),
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_return_id=return_id,
                direction="OUT", payment_method="CASH", amount=Decimal("100.00"),
                currency_code="TWD", paid_at=paid_at, note="實際退還現金",
            ),
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="BANK_DEPOSIT", direction="OUT",
                amount=Decimal("50.00"), currency_code="TWD",
                description="存入銀行", created_by_name="測試人員",
                created_at=paid_at,
            ),
        ])
        db.commit()
        db.close()

        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": "2026-11-19"},
        )
        assert response.status_code == 201, response.text
        result = response.json()

        # The return reversal is the settlement obligation; the OUT payment is
        # the actual cash refund. They are separate and must not be conflated.
        assert result["return_reversal_amount"] == "-100.00"
        assert result["collected_amount"] == "300.00"
        assert result["refunded_amount"] == "100.00"

        # A bank deposit reduces physical drawer cash, but it is not an
        # operating cash-flow expense and must not be subtracted twice.
        assert result["cash_drawer_out_amount"] == "50.00"
        assert result["net_cash_flow"] == "200.00"

        cash = next(
            item for item in result["payment_summaries"]
            if item["payment_method"] == "CASH"
        )
        assert cash["return_reversal_amount"] == "-100.00"
        assert cash["collected_amount"] == "300.00"
        assert cash["refunded_amount"] == "100.00"
        assert cash["cash_drawer_out_amount"] == "50.00"
        assert cash["net_cash_flow"] == "200.00"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

 
def test_daily_closing_includes_payment_events_at_taipei_start_but_excludes_end():
    engine, TestSession, (company_id, site_id, cash_sale_id) = _context()
    try:
        db = TestSession()
        returned = db.query(SaleReturn).filter_by(return_no="DC-RETURN").one()
        return_id = returned.id
        db.add_all([
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_id=cash_sale_id,
                direction="IN", payment_method="CASH", amount=Decimal("100.00"),
                currency_code="TWD",
                paid_at=datetime(2026, 11, 18, 15, 59, 59, tzinfo=timezone.utc),
            ),
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_id=cash_sale_id,
                direction="IN", payment_method="CASH", amount=Decimal("200.00"),
                currency_code="TWD",
                paid_at=datetime(2026, 11, 18, 16, 0, 0, tzinfo=timezone.utc),
            ),
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_return_id=return_id,
                direction="OUT", payment_method="CASH", amount=Decimal("50.00"),
                currency_code="TWD",
                paid_at=datetime(2026, 11, 19, 15, 59, 59, tzinfo=timezone.utc),
            ),
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_return_id=return_id,
                direction="OUT", payment_method="CASH", amount=Decimal("25.00"),
                currency_code="TWD",
                paid_at=datetime(2026, 11, 19, 16, 0, 0, tzinfo=timezone.utc),
            ),
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="BANK_DEPOSIT", direction="OUT",
                amount=Decimal("30.00"), currency_code="TWD",
                description="營業日內存款", created_by_name="測試人員",
                created_at=datetime(2026, 11, 19, 15, 59, 59, tzinfo=timezone.utc),
            ),
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="BANK_DEPOSIT", direction="OUT",
                amount=Decimal("10.00"), currency_code="TWD",
                description="下一營業日存款", created_by_name="測試人員",
                created_at=datetime(2026, 11, 19, 16, 0, 0, tzinfo=timezone.utc),
            ),
        ])
        db.commit()
        db.close()

        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": "2026-11-19"},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["collected_amount"] == "200.00"
        assert result["refunded_amount"] == "50.00"
        assert result["cash_drawer_out_amount"] == "30.00"
        assert result["net_cash_flow"] == "150.00"

        cash = next(
            item for item in result["payment_summaries"]
            if item["payment_method"] == "CASH"
        )
        assert cash["collected_amount"] == "200.00"
        assert cash["refunded_amount"] == "50.00"
        assert cash["cash_drawer_out_amount"] == "30.00"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_cash_count_subtracts_cash_supplier_and_expense_payments_only():
    engine, TestSession, (company_id, site_id, cash_sale_id) = _context()
    try:
        db = TestSession()
        returned = db.query(SaleReturn).filter_by(return_no="DC-RETURN").one()
        supplier = Supplier(
            company_id=company_id, code="CASH-COUNT-SUP", name="現金付款供應商"
        )
        db.add(supplier)
        db.flush()
        business_time = datetime(2026, 11, 19, 5, 0, tzinfo=timezone.utc)
        db.add_all([
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_id=cash_sale_id,
                direction="IN", payment_method="CASH", amount=Decimal("300.00"),
                currency_code="TWD", paid_at=business_time,
            ),
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_id=cash_sale_id,
                direction="IN", payment_method="CARD", amount=Decimal("500.00"),
                currency_code="TWD", paid_at=business_time,
            ),
            PaymentTransaction(
                company_id=company_id, site_id=site_id, sale_return_id=returned.id,
                direction="OUT", payment_method="CASH", amount=Decimal("50.00"),
                currency_code="TWD", paid_at=business_time,
            ),
            SupplierPayment(
                company_id=company_id, site_id=site_id, supplier_id=supplier.id,
                payment_no="SUP-CASH-001", payment_method="CASH",
                total_amount=Decimal("120.00"), currency_code="TWD",
                paid_at=business_time,
            ),
            SupplierPayment(
                company_id=company_id, site_id=site_id, supplier_id=supplier.id,
                payment_no="SUP-TRANSFER-001", payment_method="TRANSFER",
                total_amount=Decimal("200.00"), currency_code="TWD",
                paid_at=business_time,
            ),
            OperatingExpense(
                company_id=company_id, site_id=site_id, expense_no="EXP-CASH-001",
                expense_date=date(2026, 11, 19), category_code="SUPPLIES",
                description="現金購買耗材", amount=Decimal("30.00"),
                status="PAID", payment_method="CASH", paid_at=business_time,
            ),
            OperatingExpense(
                company_id=company_id, site_id=site_id, expense_no="EXP-TRANSFER-001",
                expense_date=date(2026, 11, 19), category_code="UTILITIES",
                description="轉帳支付水電", amount=Decimal("70.00"),
                status="PAID", payment_method="TRANSFER", paid_at=business_time,
            ),
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="FLOAT_INCREASE", direction="IN",
                amount=Decimal("20.00"), currency_code="TWD",
                description="增加備用金", created_by_name="測試人員",
                created_at=business_time,
            ),
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="BANK_DEPOSIT", direction="OUT",
                amount=Decimal("40.00"), currency_code="TWD",
                description="存入銀行", created_by_name="測試人員",
                created_at=business_time,
            ),
        ])
        db.commit()
        db.close()

        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": "2026-11-19"},
        )
        assert response.status_code == 201, response.text
        closing = response.json()
        cash = next(
            item for item in closing["payment_summaries"]
            if item["payment_method"] == "CASH"
        )
        assert cash["collected_amount"] == "300.00"
        assert cash["refunded_amount"] == "50.00"
        assert cash["supplier_paid_amount"] == "120.00"
        assert cash["expenses_paid_amount"] == "30.00"
        assert cash["cash_drawer_in_amount"] == "20.00"
        assert cash["cash_drawer_out_amount"] == "40.00"
        assert cash["net_cash_flow"] == "100.00"

        counted = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings/"
            f"{closing['id']}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "580.00",
                "counted_by_name": "盤點人甲",
            },
        )
        assert counted.status_code == 201, counted.text
        assert counted.json()["expected_cash_amount"] == "580.00"
        assert counted.json()["cash_variance"] == "0.00"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_closed_day_rejects_immediate_operating_expense_payment():
    from app.services.operating_expenses import create_expense

    engine, TestSession, (company_id, site_id, _) = _context()
    try:
        db = TestSession()
        business_date = date.today()
        create_daily_closing(
            db, company_id=company_id, site_id=site_id,
            business_date=business_date,
        )
        db.commit()
        try:
            create_expense(
                db, company_id=company_id, site_id=site_id,
                expense_no="AFTER-CLOSE-EXP", expense_date=business_date,
                category_code="SUPPLIES", description="結帳後新增的現金費用",
                amount=Decimal("25.00"), payment_method="CASH",
            )
            assert False, "closed day must reject an immediately paid expense"
        except ValueError as exc:
            assert "已結帳" in str(exc)
        db.rollback()
        assert db.query(OperatingExpense).count() == 0
        db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_closed_day_rejects_cash_drawer_movement_after_daily_close():
    from app.services.cash_drawer_movements import create_cash_drawer_movement

    engine, TestSession, (company_id, site_id, _) = _context()
    try:
        db = TestSession()
        business_date = date.today()
        create_daily_closing(
            db, company_id=company_id, site_id=site_id,
            business_date=business_date,
        )
        db.commit()
        try:
            create_cash_drawer_movement(
                db, company_id=company_id, site_id=site_id,
                movement_type="BANK_DEPOSIT", amount=Decimal("100.00"),
                description="結帳後才登錄的存款", created_by_name="測試人員",
            )
            assert False, "closed day must reject a later drawer movement"
        except ValueError as exc:
            assert "已結帳" in str(exc)
        db.rollback()
        assert db.query(CashDrawerMovement).count() == 0
        db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
