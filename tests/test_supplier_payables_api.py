from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.daily_closing import DailyClosing
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill, SupplierPayment
from app.routers import daily_closing, supplier_payables, suppliers


def _payable_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="AP-TEST", name="應付帳款測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    session.add_all([site, supplier])
    session.commit()
    ids = (company.id, site.id, supplier.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[supplier_payables.get_db] = override_db
    app.dependency_overrides[suppliers.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    return engine, TestSession, ids


def test_supplier_master_create_and_list():
    engine, _TestSession, (company_id, _site_id, _supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        response = client.post(f"/companies/{company_id}/suppliers", json={
            "code": "SUP-02",
            "name": "新增測試供應商",
            "tax_id": "12345678",
            "contact_name": "王小姐",
            "phone": "02-12345678",
        })
        assert response.status_code == 201, response.text
        assert response.json()["name"] == "新增測試供應商"
        listed = client.get(f"/companies/{company_id}/suppliers")
        assert listed.status_code == 200, listed.text
        assert {row["code"] for row in listed.json()} == {"SUP-01", "SUP-02"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_bills_partial_payments_and_daily_cash_outflow():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        bill1 = client.post(f"{base}/bills", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "bill_no": "INV-001", "bill_date": "2026-11-19",
            "due_date": "2026-12-19", "currency_code": "TWD",
            "total_amount": "1000.00",
        })
        assert bill1.status_code == 201, bill1.text
        bill2 = client.post(f"{base}/bills", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "bill_no": "INV-002", "bill_date": "2026-11-19",
            "currency_code": "TWD", "total_amount": "500.00",
        })
        assert bill2.status_code == 201, bill2.text

        listed_bills = client.get(f"{base}/bills", params={"site_id": str(site_id)})
        assert listed_bills.status_code == 200, listed_bills.text
        assert len(listed_bills.json()) == 2

        payment1 = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-001", "payment_method": "TRANSFER",
            "reference_no": "BANK-001",
            "allocations": [
                {"bill_id": bill1.json()["id"], "amount": "700.00"},
                {"bill_id": bill2.json()["id"], "amount": "500.00"},
            ],
        })
        assert payment1.status_code == 201, payment1.text
        assert payment1.json()["total_amount"] == "1200.00"
        assert len(payment1.json()["allocations"]) == 2

        listed_payments = client.get(f"{base}/payments", params={"site_id": str(site_id)})
        assert listed_payments.status_code == 200, listed_payments.text
        assert len(listed_payments.json()) == 1

        refreshed1 = client.get(f"{base}/bills/{bill1.json()['id']}")
        refreshed2 = client.get(f"{base}/bills/{bill2.json()['id']}")
        assert refreshed1.json()["status"] == "PARTIALLY_PAID"
        assert refreshed1.json()["paid_amount"] == "700.00"
        assert refreshed1.json()["outstanding_amount"] == "300.00"
        assert refreshed2.json()["status"] == "PAID"
        assert refreshed2.json()["outstanding_amount"] == "0.00"

        overpay = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-OVER", "payment_method": "CASH",
            "allocations": [{"bill_id": bill1.json()["id"], "amount": "300.01"}],
        })
        assert overpay.status_code == 422

        payment2 = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-002", "payment_method": "CASH",
            "allocations": [{"bill_id": bill1.json()["id"], "amount": "300.00"}],
        })
        assert payment2.status_code == 201, payment2.text
        final_bill = client.get(f"{base}/bills/{bill1.json()['id']}")
        assert final_bill.json()["status"] == "PAID"
        assert final_bill.json()["outstanding_amount"] == "0.00"

        business_date = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
        close = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text
        assert close.json()["supplier_paid_amount"] == "1500.00"
        assert close.json()["net_cash_flow"] == "-1500.00"
        summaries = {x["payment_method"]: x for x in close.json()["payment_summaries"]}
        assert summaries["TRANSFER"]["supplier_paid_amount"] == "1200.00"
        assert summaries["CASH"]["supplier_paid_amount"] == "300.00"

        check = TestSession()
        assert check.query(SupplierBill).count() == 2
        assert check.query(SupplierPayment).count() == 2
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_payment_rejects_mixed_currency_and_duplicate_bill_allocation():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        ids = []
        for bill_no, currency in [("INV-TWD", "TWD"), ("INV-USD", "USD")]:
            response = client.post(f"{base}/bills", json={
                "site_id": str(site_id), "supplier_id": str(supplier_id),
                "bill_no": bill_no, "bill_date": "2026-11-19",
                "currency_code": currency, "total_amount": "100.00",
            })
            assert response.status_code == 201, response.text
            ids.append(response.json()["id"])

        foreign_payment = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-USD", "payment_method": "TRANSFER",
            "allocations": [{"bill_id": ids[1], "amount": "50.00"}],
        })
        assert foreign_payment.status_code == 422
        assert "新台幣" in foreign_payment.json()["detail"]

        mixed = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-MIX", "payment_method": "TRANSFER",
            "allocations": [
                {"bill_id": ids[0], "amount": "50.00"},
                {"bill_id": ids[1], "amount": "50.00"},
            ],
        })
        assert mixed.status_code == 422
        duplicate = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-DUP", "payment_method": "TRANSFER",
            "allocations": [
                {"bill_id": ids[0], "amount": "20.00"},
                {"bill_id": ids[0], "amount": "20.00"},
            ],
        })
        assert duplicate.status_code == 422
        check = TestSession()
        assert check.query(SupplierPayment).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
