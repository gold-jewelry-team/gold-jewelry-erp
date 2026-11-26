from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.operating_expense import OperatingExpense
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierPayment, SupplierPaymentReversal
from app.routers import operational_reports


def _operational_report_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    company = Company(code="OPER-RPT", name="營運報表測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()

    inside = datetime(2026, 11, 19, 15, 59, 59, tzinfo=timezone.utc)
    period_end = datetime(2026, 11, 19, 16, 0, 0, tzinfo=timezone.utc)
    sale_twd = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="RPT-TWD-IN",
        status="COMPLETED",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("1000.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("1000.00"),
        completed_at=inside,
    )
    sale_usd = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="RPT-USD-IN",
        status="COMPLETED",
        payment_method="TRANSFER",
        currency_code="USD",
        subtotal=Decimal("10.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("10.00"),
        completed_at=inside,
    )
    sale_next_day = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="RPT-NEXT-DAY",
        status="COMPLETED",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("500.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("500.00"),
        completed_at=period_end,
    )
    sale_draft = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="RPT-DRAFT",
        status="DRAFT",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("999.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("999.00"),
        completed_at=inside,
    )
    db.add_all([sale_twd, sale_usd, sale_next_day, sale_draft])
    db.flush()

    returned = SaleReturn(
        company_id=company.id,
        site_id=site.id,
        sale_id=sale_twd.id,
        return_no="RPT-RETURN",
        settlement_reversal_amount=Decimal("-100.00"),
        currency_code="TWD",
        created_at=inside,
    )
    db.add(returned)
    db.flush()

    order = CustomerOrder(
        company_id=company.id,
        site_id=site.id,
        order_no="RPT-ORDER",
        status="PENDING_DEPOSIT",
        customer_name="報表客訂客戶",
        currency_code="TWD",
        items=[],
        total_amount=Decimal("200.00"),
        deposit_amount=Decimal("80.00"),
        created_at=inside,
    )
    supplier = Supplier(
        company_id=company.id,
        code="RPT-SUP",
        name="報表測試供應商",
    )
    db.add_all([order, supplier])
    db.flush()

    db.add_all([
        PaymentTransaction(
            company_id=company.id, site_id=site.id, sale_id=sale_twd.id,
            direction="IN", payment_method="CASH", amount=Decimal("300.00"),
            currency_code="TWD", paid_at=inside, note="銷售部分收款",
        ),
        PaymentTransaction(
            company_id=company.id, site_id=site.id, sale_return_id=returned.id,
            direction="OUT", payment_method="CASH", amount=Decimal("50.00"),
            currency_code="TWD", paid_at=inside, note="退貨部分退款",
        ),
        PaymentTransaction(
            company_id=company.id, site_id=site.id, customer_order_id=order.id,
            direction="IN", payment_method="TRANSFER", amount=Decimal("80.00"),
            currency_code="TWD", paid_at=inside, note="客訂訂金",
        ),
        PaymentTransaction(
            company_id=company.id, site_id=site.id, sale_id=sale_twd.id,
            direction="IN", payment_method="CASH", amount=Decimal("700.00"),
            currency_code="TWD", paid_at=period_end, note="下一營業日收款",
        ),
    ])

    supplier_payment = SupplierPayment(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        payment_no="RPT-SUP-PAY", payment_method="CASH",
        total_amount=Decimal("40.00"), currency_code="TWD", paid_at=inside,
    )
    db.add_all([
        supplier_payment,
        OperatingExpense(
            company_id=company.id, site_id=site.id, expense_no="RPT-EXP",
            expense_date=date(2026, 11, 19), category_code="SUPPLIES",
            description="現金購買耗材", amount=Decimal("20.00"),
            currency_code="TWD", status="PAID", payment_method="CASH",
            paid_at=inside,
        ),
        CashDrawerMovement(
            company_id=company.id, site_id=site.id,
            movement_type="BANK_DEPOSIT", direction="OUT",
            amount=Decimal("10.00"), currency_code="TWD",
            description="存入銀行", created_by_name="報表測試人員",
            created_at=inside,
        ),
    ])
    db.flush()
    db.add(SupplierPaymentReversal(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        payment_id=supplier_payment.id,
        reversal_no="RPT-SUP-REV",
        total_amount=Decimal("15.00"),
        currency_code="TWD",
        reversed_at=inside,
        reason="報表測試：退回部分供應商付款",
    ))
    db.commit()
    ids = (company.id, site.id)
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[operational_reports.get_db] = override_db
    return engine, ids


def test_operational_period_report_keeps_sales_obligations_receipts_and_outflows_separate():
    engine, (company_id, site_id) = _operational_report_context()
    try:
        client = TestClient(app)
        response = client.get(
            f"/companies/{company_id}/sites/{site_id}/operational-report",
            params={"period_start": "2026-11-19", "period_end": "2026-11-19"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["timezone"] == "Asia/Taipei"
        assert result["site_name"] == "總店"
        assert len(result["totals_by_currency"]) == 2

        twd = next(row for row in result["totals_by_currency"] if row["currency_code"] == "TWD")
        assert twd["sales_count"] == 1
        assert twd["gross_sales_amount"] == "1000.00"
        assert twd["returns_count"] == 1
        assert twd["return_reversal_amount"] == "-100.00"
        assert twd["net_sales_amount"] == "900.00"

        # Collections are based on paid_at, and customer-order deposits are
        # reported separately rather than being treated as completed sales.
        assert twd["sales_collected_amount"] == "300.00"
        assert twd["return_refunded_amount"] == "50.00"
        assert twd["customer_order_collected_amount"] == "80.00"
        assert twd["customer_collected_amount"] == "380.00"
        assert twd["customer_refunded_amount"] == "50.00"

        assert twd["supplier_payment_count"] == 1
        assert twd["supplier_paid_amount"] == "40.00"
        assert twd["supplier_payment_reversed_amount"] == "15.00"
        assert twd["paid_expense_count"] == 1
        assert twd["expenses_paid_amount"] == "20.00"
        assert twd["net_operating_cash_flow"] == "285.00"

        # Physical cash includes cash supplier-payment reversals as an inflow.
        assert twd["cash_drawer_out_amount"] == "10.00"
        assert twd["expected_cash_change"] == "195.00"
        cash_method = next(
            row for row in twd["payment_methods"]
            if row["payment_method"] == "CASH"
        )
        assert cash_method["customer_collected_amount"] == "300.00"
        assert cash_method["customer_refunded_amount"] == "50.00"
        assert cash_method["supplier_paid_amount"] == "40.00"
        assert cash_method["supplier_payment_reversed_amount"] == "15.00"
        assert cash_method["expenses_paid_amount"] == "20.00"
        assert cash_method["net_operating_cash_flow"] == "205.00"

        twd_day = next(
            row for row in result["daily"]
            if row["currency_code"] == "TWD"
        )
        assert twd_day["supplier_payment_reversed_amount"] == "15.00"
        assert twd_day["net_operating_cash_flow"] == "285.00"
        assert twd_day["expected_cash_change"] == "195.00"

        usd = next(row for row in result["totals_by_currency"] if row["currency_code"] == "USD")
        assert usd["gross_sales_amount"] == "10.00"
        assert usd["net_sales_amount"] == "10.00"

        # The exact Taipei day-end is exclusive: the next-day sale and
        # payment are not silently included in the selected period.
        assert twd["gross_sales_amount"] != "1500.00"
        assert twd["customer_collected_amount"] != "1080.00"

        assert len(result["daily"]) == 2
        checks = result["integrity_checks"]
        assert len(checks) == 14  # Seven arithmetic checks for each currency.
        assert {check["status"] for check in checks} == {"PASS"}
        assert {check["code"] for check in checks} == {
            "net_sales",
            "customer_collected_sources",
            "customer_refunded_sources",
            "net_operating_cash_flow",
            "expected_cash_change",
            "daily_totals",
            "payment_method_totals",
        }
        assert {check["currency_code"] for check in checks} == {"TWD", "USD"}
        assert {row["business_date"] for row in result["daily"]} == {"2026-11-19"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_operational_period_report_validates_date_range_and_company_site_scope():
    engine, (company_id, site_id) = _operational_report_context()
    try:
        client = TestClient(app)
        invalid_range = client.get(
            f"/companies/{company_id}/sites/{site_id}/operational-report",
            params={"period_start": "2026-11-20", "period_end": "2026-11-19"},
        )
        assert invalid_range.status_code == 422

        unknown_scope = client.get(
            f"/companies/{company_id}/sites/00000000-0000-0000-0000-000000000001/operational-report",
            params={"period_start": "2026-11-19", "period_end": "2026-11-19"},
        )
        assert unknown_scope.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
