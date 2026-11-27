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
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import (
    SupplierBill,
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierPaymentReversal,
    SupplierPaymentReversalAllocation,
)
from app.routers import supplier_payables


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        company = Company(code="PAYABLE-AGING", name="帳齡摘要測試公司")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        other_site = Site(company_id=company.id, code="BRANCH", name="分店")
        supplier = Supplier(company_id=company.id, code="SUP-AGING", name="帳齡測試供應商")
        supplier_two = Supplier(company_id=company.id, code="SUP-AGING-2", name="第二家供應商")
        db.add_all([site, other_site, supplier, supplier_two])
        db.flush()

        bills = {
            "overdue_30": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                bill_no="AGING-30", bill_date=date(2026, 10, 1),
                due_date=date(2026, 10, 27), currency_code="TWD",
                total_amount=Decimal("1000.00"), status="PARTIALLY_PAID",
            ),
            "overdue_61": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                bill_no="AGING-61", bill_date=date(2026, 8, 1),
                due_date=date(2026, 9, 26), currency_code="TWD",
                total_amount=Decimal("500.00"), status="OPEN",
            ),
            "not_due": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                bill_no="AGING-FUTURE", bill_date=date(2026, 11, 1),
                due_date=date(2026, 12, 10), currency_code="TWD",
                total_amount=Decimal("250.00"), status="OPEN",
            ),
            "no_due": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                bill_no="AGING-NO-DUE", bill_date=date(2026, 10, 10),
                due_date=None, currency_code="USD",
                total_amount=Decimal("400.00"), status="OPEN",
            ),
            "paid": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                bill_no="AGING-PAID", bill_date=date(2026, 10, 1),
                due_date=date(2026, 10, 15), currency_code="TWD",
                total_amount=Decimal("120.00"), status="PAID",
            ),
            "void": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                bill_no="AGING-VOID", bill_date=date(2026, 10, 1),
                due_date=date(2026, 10, 15), currency_code="TWD",
                total_amount=Decimal("700.00"), status="VOID",
            ),
            "other_site": SupplierBill(
                company_id=company.id, site_id=other_site.id, supplier_id=supplier.id,
                bill_no="AGING-OTHER-SITE", bill_date=date(2026, 10, 1),
                due_date=date(2026, 10, 1), currency_code="TWD",
                total_amount=Decimal("900.00"), status="OPEN",
            ),
            "other_supplier": SupplierBill(
                company_id=company.id, site_id=site.id, supplier_id=supplier_two.id,
                bill_no="AGING-OTHER-SUPPLIER", bill_date=date(2026, 7, 1),
                due_date=date(2026, 8, 27), currency_code="TWD",
                total_amount=Decimal("300.00"), status="OPEN",
            ),
        }
        db.add_all(bills.values())
        db.flush()

        partial_payment = SupplierPayment(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            payment_no="AGING-PAY-1", payment_method="TRANSFER",
            total_amount=Decimal("300.00"), currency_code="TWD",
            paid_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
        )
        fully_paid_payment = SupplierPayment(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            payment_no="AGING-PAY-2", payment_method="CASH",
            total_amount=Decimal("120.00"), currency_code="TWD",
            paid_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
        )
        db.add_all([partial_payment, fully_paid_payment])
        db.flush()
        partial_allocation = SupplierPaymentAllocation(
            payment_id=partial_payment.id, bill_id=bills["overdue_30"].id,
            amount=Decimal("300.00"),
        )
        fully_paid_allocation = SupplierPaymentAllocation(
            payment_id=fully_paid_payment.id, bill_id=bills["paid"].id,
            amount=Decimal("120.00"),
        )
        db.add_all([partial_allocation, fully_paid_allocation])
        db.flush()

        reversal = SupplierPaymentReversal(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            payment_id=partial_payment.id, reversal_no="AGING-REV-1",
            total_amount=Decimal("100.00"), currency_code="TWD",
            reversed_at=datetime(2026, 11, 22, tzinfo=timezone.utc),
            reason="部分退回",
        )
        db.add(reversal)
        db.flush()
        db.add(SupplierPaymentReversalAllocation(
            reversal_id=reversal.id,
            payment_allocation_id=partial_allocation.id,
            amount=Decimal("100.00"),
        ))
        db.commit()
        ids = (company.id, site.id, supplier.id, supplier_two.id)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[supplier_payables.get_db] = override_db
    return engine, ids


def test_supplier_payable_aging_groups_net_balances_by_supplier_currency_and_due_bucket():
    engine, (company_id, site_id, supplier_id, supplier_two_id) = _context()
    try:
        client = TestClient(app)
        response = client.get(
            f"/companies/{company_id}/supplier-payables/aging",
            params={"as_of_date": "2026-11-26", "site_id": str(site_id)},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["as_of_date"] == "2026-11-26"

        rows = {(row["supplier_id"], row["currency_code"]): row for row in data["rows"]}
        main_twd = rows[(str(supplier_id), "TWD")]
        assert main_twd["outstanding_bill_count"] == 3
        assert main_twd["overdue_bill_count"] == 2
        assert main_twd["total_outstanding"] == "1550.00"
        assert main_twd["overdue_1_30_amount"] == "800.00"
        assert main_twd["overdue_61_90_amount"] == "500.00"
        assert main_twd["not_due_amount"] == "250.00"
        assert main_twd["no_due_date_amount"] == "0.00"

        main_usd = rows[(str(supplier_id), "USD")]
        assert main_usd["total_outstanding"] == "400.00"
        assert main_usd["no_due_date_amount"] == "400.00"

        other_twd = rows[(str(supplier_two_id), "TWD")]
        assert other_twd["overdue_91_plus_amount"] == "300.00"

        filtered = client.get(
            f"/companies/{company_id}/supplier-payables/aging",
            params={
                "as_of_date": "2026-11-26",
                "site_id": str(site_id),
                "supplier_id": str(supplier_id),
            },
        )
        assert filtered.status_code == 200, filtered.text
        assert len(filtered.json()["rows"]) == 2
        assert {row["supplier_id"] for row in filtered.json()["rows"]} == {str(supplier_id)}
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
