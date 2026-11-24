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
from app.models.customer_order import CustomerOrder
from app.models.gold_material import GoldMaterialMovement, GoldMaterialSettlementAllocation
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import (
    SupplierBill,
    SupplierPayment,
    SupplierPaymentAllocation,
)
from app.routers import operational_reports


def test_operational_report_lists_current_open_balances_by_currency_and_source():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    company = Company(code="OPEN-BAL", name="未結清帳款測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-OPEN", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()
    event_time = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)

    sale = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="OPEN-SALE-001",
        status="COMPLETED",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("1000.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("1000.00"),
        completed_at=event_time,
    )
    usd_sale = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="OPEN-SALE-USD",
        status="COMPLETED",
        payment_method="TRANSFER",
        currency_code="USD",
        subtotal=Decimal("200.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("200.00"),
        completed_at=event_time,
    )
    db.add_all([sale, usd_sale])
    db.flush()

    returned = SaleReturn(
        company_id=company.id,
        site_id=site.id,
        sale_id=sale.id,
        return_no="OPEN-RETURN-001",
        settlement_reversal_amount=Decimal("-100.00"),
        currency_code="TWD",
        created_at=event_time,
    )
    order = CustomerOrder(
        company_id=company.id,
        site_id=site.id,
        order_no="OPEN-ORDER-001",
        status="IN_PROGRESS",
        customer_name="客訂測試客戶",
        currency_code="TWD",
        items=[{"name": "測試商品"}],
        total_amount=Decimal("500.00"),
        deposit_amount=Decimal("100.00"),
        expected_delivery_date=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
        created_at=event_time,
    )
    bill = SupplierBill(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        bill_no="OPEN-BILL-001",
        bill_date=date(2026, 11, 19),
        due_date=date(2026, 11, 20),
        currency_code="TWD",
        total_amount=Decimal("1000.00"),
        status="PARTIALLY_PAID",
    )
    db.add_all([returned, order, bill])
    db.flush()

    cash_payment = SupplierPayment(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        payment_no="OPEN-SUP-PAY-001",
        payment_method="TRANSFER",
        total_amount=Decimal("300.00"),
        currency_code="TWD",
        paid_at=event_time,
    )
    gold_movement = GoldMaterialMovement(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        movement_no="OPEN-GOLD-001",
        movement_type="SUPPLIER_DELIVERY",
        purity_label="9999",
        purity_ratio=Decimal("0.9999"),
        gross_weight=Decimal("1.0000"),
        loss_weight=Decimal("0.0000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="G",
        fine_gold_weight_g=Decimal("0.9999"),
        gold_price_value=Decimal("3000.00"),
        gold_price_unit_code="G",
        deduction_amount=Decimal("0.00"),
        valuation_amount=Decimal("200.00"),
        occurred_at=event_time,
    )
    db.add_all([cash_payment, gold_movement])
    db.flush()

    db.add_all([
        SupplierPaymentAllocation(
            payment_id=cash_payment.id,
            bill_id=bill.id,
            amount=Decimal("300.00"),
        ),
        GoldMaterialSettlementAllocation(
            movement_id=gold_movement.id,
            bill_id=bill.id,
            amount=Decimal("200.00"),
        ),
        PaymentTransaction(
            company_id=company.id,
            site_id=site.id,
            sale_id=sale.id,
            direction="IN",
            payment_method="CASH",
            amount=Decimal("300.00"),
            currency_code="TWD",
            paid_at=event_time,
        ),
        PaymentTransaction(
            company_id=company.id,
            site_id=site.id,
            sale_return_id=returned.id,
            direction="OUT",
            payment_method="CASH",
            amount=Decimal("40.00"),
            currency_code="TWD",
            paid_at=event_time,
        ),
        PaymentTransaction(
            company_id=company.id,
            site_id=site.id,
            customer_order_id=order.id,
            direction="IN",
            payment_method="CASH",
            amount=Decimal("100.00"),
            currency_code="TWD",
            paid_at=event_time,
        ),
    ])
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[operational_reports.get_db] = override_db
    try:
        response = TestClient(app).get(
            f"/companies/{company_id}/sites/{site_id}/operational-report",
            params={"period_start": "2026-11-19", "period_end": "2026-11-19"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        outstanding = result["outstanding_balances"]
        summaries = {row["currency_code"]: row for row in outstanding["summaries_by_currency"]}
        assert summaries["TWD"]["total_receivable"] == "1100.00"
        assert summaries["TWD"]["total_payable"] == "560.00"
        assert summaries["USD"]["total_receivable"] == "200.00"
        assert summaries["USD"]["total_payable"] == "0.00"

        items = {row["document_no"]: row for row in outstanding["items"]}
        assert items["OPEN-SALE-001"]["amount"] == "700.00"
        assert items["OPEN-SALE-001"]["source_target"] == "salesPanel"
        assert items["OPEN-RETURN-001"]["amount"] == "60.00"
        assert items["OPEN-RETURN-001"]["category_label"] == "退貨待退款"
        assert items["OPEN-RETURN-001"]["side"] == "PAYABLE"
        assert items["OPEN-RETURN-001"]["source_target"] == "salesPanel"
        assert items["OPEN-ORDER-001"]["amount"] == "400.00"
        assert items["OPEN-ORDER-001"]["source_target"] == "customerOrderList"
        assert items["OPEN-BILL-001"]["amount"] == "500.00"
        assert items["OPEN-BILL-001"]["source_target"] == "supplierPayablesPanel"
        assert items["OPEN-BILL-001"]["days_overdue"] is not None
        assert items["OPEN-SALE-USD"]["currency_code"] == "USD"
        assert len(summaries) == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
