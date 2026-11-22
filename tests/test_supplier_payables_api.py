from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from uuid import UUID

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


def test_supplier_payment_is_blocked_after_daily_closing():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        bill = client.post(f"{base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-CLOSED-001",
            "bill_date": "2026-11-20",
            "currency_code": "TWD",
            "total_amount": "1200.00",
        })
        assert bill.status_code == 201, bill.text

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text

        payment = client.post(f"{base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-CLOSED-001",
            "payment_method": "TRANSFER",
            "allocations": [{
                "bill_id": bill.json()["id"],
                "amount": "500.00",
            }],
        })
        assert payment.status_code == 422
        assert "已結帳" in payment.json()["detail"]

        refreshed = client.get(f"{base}/bills/{bill.json()['id']}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "OPEN"
        assert Decimal(refreshed.json()["paid_amount"]) == Decimal("0.00")
        assert refreshed.json()["outstanding_amount"] == "1200.00"

        check = TestSession()
        assert check.query(SupplierPayment).count() == 0
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_payment_with_void_bill_is_atomic_across_all_allocations():
    from app.models.supplier_payable import SupplierPaymentAllocation

    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        created_bills = []
        for bill_no in ("INV-ATOMIC-001", "INV-ATOMIC-002"):
            response = client.post(f"{base}/bills", json={
                "site_id": str(site_id),
                "supplier_id": str(supplier_id),
                "bill_no": bill_no,
                "bill_date": "2026-11-22",
                "currency_code": "TWD",
                "total_amount": "100.00",
            })
            assert response.status_code == 201, response.text
            created_bills.append(response.json())

        # The first allocation is valid, but the second bill is void.
        # The service must validate every bill before creating any payment row.
        db = TestSession()
        void_bill = db.get(SupplierBill, UUID(created_bills[1]["id"]))
        void_bill.status = "VOID"
        db.commit()
        db.close()

        rejected = client.post(f"{base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-ATOMIC-VOID",
            "payment_method": "TRANSFER",
            "allocations": [
                {"bill_id": created_bills[0]["id"], "amount": "40.00"},
                {"bill_id": created_bills[1]["id"], "amount": "40.00"},
            ],
        })
        assert rejected.status_code == 422, rejected.text
        assert "作廢" in rejected.json()["detail"]

        first_bill = client.get(f"{base}/bills/{created_bills[0]['id']}")
        second_bill = client.get(f"{base}/bills/{created_bills[1]['id']}")
        assert first_bill.status_code == 200
        assert first_bill.json()["status"] == "OPEN"
        assert Decimal(first_bill.json()["paid_amount"]) == Decimal("0.00")
        assert first_bill.json()["outstanding_amount"] == "100.00"
        assert second_bill.json()["status"] == "VOID"
        assert Decimal(second_bill.json()["paid_amount"]) == Decimal("0.00")

        check = TestSession()
        assert check.query(SupplierPayment).count() == 0
        assert check.query(SupplierPaymentAllocation).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_duplicate_supplier_payment_number_rolls_back_second_allocation():
    from app.models.supplier_payable import SupplierPaymentAllocation

    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        bill = client.post(f"{base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-DUP-PAYNO",
            "bill_date": "2026-11-22",
            "currency_code": "TWD",
            "total_amount": "200.00",
        })
        assert bill.status_code == 201, bill.text

        first = client.post(f"{base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-DUPLICATE-NO",
            "payment_method": "TRANSFER",
            "allocations": [{"bill_id": bill.json()["id"], "amount": "50.00"}],
        })
        assert first.status_code == 201, first.text

        duplicate = client.post(f"{base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-DUPLICATE-NO",
            "payment_method": "CASH",
            "allocations": [{"bill_id": bill.json()["id"], "amount": "70.00"}],
        })
        assert duplicate.status_code == 409, duplicate.text

        refreshed = client.get(f"{base}/bills/{bill.json()['id']}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "PARTIALLY_PAID"
        assert Decimal(refreshed.json()["paid_amount"]) == Decimal("50.00")
        assert Decimal(refreshed.json()["outstanding_amount"]) == Decimal("150.00")

        check = TestSession()
        assert check.query(SupplierPayment).count() == 1
        assert check.query(SupplierPaymentAllocation).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_supplier_payment_rejects_cross_supplier_bill_without_partial_allocation():
    from app.models.supplier_payable import SupplierPaymentAllocation

    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        other_supplier = client.post(f"/companies/{company_id}/suppliers", json={
            "code": "SUP-OTHER",
            "name": "另一家供應商",
        })
        assert other_supplier.status_code == 201, other_supplier.text
        other_supplier_id = other_supplier.json()["id"]

        own_bill = client.post(f"{base}/bills", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "bill_no": "INV-OWN-ATOMIC", "bill_date": "2026-11-22",
            "currency_code": "TWD", "total_amount": "100.00",
        })
        foreign_bill = client.post(f"{base}/bills", json={
            "site_id": str(site_id), "supplier_id": other_supplier_id,
            "bill_no": "INV-FOREIGN-ATOMIC", "bill_date": "2026-11-22",
            "currency_code": "TWD", "total_amount": "100.00",
        })
        assert own_bill.status_code == 201, own_bill.text
        assert foreign_bill.status_code == 201, foreign_bill.text

        rejected = client.post(f"{base}/payments", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "payment_no": "SP-CROSS-SUPPLIER", "payment_method": "TRANSFER",
            "allocations": [
                {"bill_id": own_bill.json()["id"], "amount": "40.00"},
                {"bill_id": foreign_bill.json()["id"], "amount": "40.00"},
            ],
        })
        assert rejected.status_code == 422, rejected.text
        assert "相同公司、據點及供應商" in rejected.json()["detail"]

        refreshed_own = client.get(f"{base}/bills/{own_bill.json()['id']}")
        refreshed_foreign = client.get(f"{base}/bills/{foreign_bill.json()['id']}")
        assert refreshed_own.json()["status"] == "OPEN"
        assert Decimal(refreshed_own.json()["paid_amount"]) == Decimal("0.00")
        assert refreshed_foreign.json()["status"] == "OPEN"
        assert Decimal(refreshed_foreign.json()["paid_amount"]) == Decimal("0.00")

        check = TestSession()
        assert check.query(SupplierPayment).count() == 0
        assert check.query(SupplierPaymentAllocation).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_duplicate_supplier_bill_number_is_rejected_without_creating_second_bill():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        payload = {
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-DUPLICATE-SUPPLIER",
            "bill_date": "2026-11-22",
            "currency_code": "TWD",
            "total_amount": "125.00",
        }
        first = client.post(f"{base}/bills", json=payload)
        assert first.status_code == 201, first.text

        duplicate = client.post(f"{base}/bills", json={
            **payload,
            "total_amount": "999.00",
        })
        assert duplicate.status_code == 409, duplicate.text
        assert "帳單號碼重複" in duplicate.json()["detail"]

        listed = client.get(f"{base}/bills", params={"site_id": str(site_id)})
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == first.json()["id"]
        assert Decimal(listed.json()[0]["total_amount"]) == Decimal("125.00")
        assert listed.json()[0]["status"] == "OPEN"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_same_supplier_bill_number_is_allowed_for_different_suppliers():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        other_supplier = client.post(f"/companies/{company_id}/suppliers", json={
            "code": "SUP-SECOND",
            "name": "第二家供應商",
        })
        assert other_supplier.status_code == 201, other_supplier.text

        shared_bill_no = "INV-SHARED-ACROSS-SUPPLIERS"
        first = client.post(f"{base}/bills", json={
            "site_id": str(site_id), "supplier_id": str(supplier_id),
            "bill_no": shared_bill_no, "bill_date": "2026-11-22",
            "currency_code": "TWD", "total_amount": "125.00",
        })
        second = client.post(f"{base}/bills", json={
            "site_id": str(site_id), "supplier_id": other_supplier.json()["id"],
            "bill_no": shared_bill_no, "bill_date": "2026-11-22",
            "currency_code": "TWD", "total_amount": "225.00",
        })
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["id"] != second.json()["id"]
        assert first.json()["bill_no"] == second.json()["bill_no"] == shared_bill_no

        listed = client.get(f"{base}/bills", params={"site_id": str(site_id)})
        assert listed.status_code == 200, listed.text
        matching = [item for item in listed.json() if item["bill_no"] == shared_bill_no]
        assert len(matching) == 2
        assert {item["supplier_id"] for item in matching} == {
            str(supplier_id), other_supplier.json()["id"]
        }
        check = TestSession()
        assert check.query(SupplierBill).count() == 2
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_bill_cannot_be_created_from_cancelled_purchase():
    from app.models.purchase import Purchase
    from app.services.supplier_payables import create_supplier_bill

    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    session = TestSession()
    try:
        purchase = Purchase(
            company_id=company_id,
            site_id=site_id,
            supplier_id=supplier_id,
            purchase_no="PO-CANCELLED-BILL",
            order_date=date(2026, 11, 22),
            currency_code="TWD",
            status="CANCELLED",
        )
        session.add(purchase)
        session.commit()
        purchase_id = purchase.id

        try:
            create_supplier_bill(
                session,
                company_id=company_id,
                site_id=site_id,
                supplier_id=supplier_id,
                purchase_id=purchase_id,
                bill_no="INV-FROM-CANCELLED-PO",
                bill_date=date(2026, 11, 22),
                due_date=None,
                currency_code="TWD",
                total_amount=Decimal("300.00"),
            )
            assert False, "取消的採購單不應建立供應商應付帳單"
        except ValueError as exc:
            assert "採購單狀態不允許" in str(exc)

        session.rollback()
        assert session.query(SupplierBill).count() == 0
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_bill_rejects_purchase_from_another_supplier():
    from app.models.purchase import Purchase
    from app.services.supplier_payables import create_supplier_bill

    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    session = TestSession()
    try:
        other_supplier = Supplier(
            company_id=company_id,
            code="SUP-OTHER",
            name="另一家供應商",
        )
        session.add(other_supplier)
        session.flush()
        purchase = Purchase(
            company_id=company_id,
            site_id=site_id,
            supplier_id=supplier_id,
            purchase_no="PO-SUPPLIER-MISMATCH",
            order_date=date(2026, 11, 22),
            currency_code="TWD",
            status="ORDERED",
        )
        session.add(purchase)
        session.commit()
        other_supplier_id = other_supplier.id
        purchase_id = purchase.id

        try:
            create_supplier_bill(
                session,
                company_id=company_id,
                site_id=site_id,
                supplier_id=other_supplier_id,
                purchase_id=purchase_id,
                bill_no="INV-WRONG-SUPPLIER",
                bill_date=date(2026, 11, 22),
                due_date=None,
                currency_code="TWD",
                total_amount=Decimal("450.00"),
            )
            assert False, "帳單供應商必須與關聯採購單供應商一致"
        except ValueError as exc:
            assert "供應商／據點不符" in str(exc)

        session.rollback()
        assert session.query(SupplierBill).count() == 0
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_bill_rejects_purchase_from_another_site():
    from app.models.purchase import Purchase
    from app.services.supplier_payables import create_supplier_bill

    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    session = TestSession()
    try:
        other_site = Site(company_id=company_id, code="BRANCH", name="分店")
        session.add(other_site)
        session.flush()
        purchase = Purchase(
            company_id=company_id,
            site_id=site_id,
            supplier_id=supplier_id,
            purchase_no="PO-SITE-MISMATCH",
            order_date=date(2026, 11, 22),
            currency_code="TWD",
            status="ORDERED",
        )
        session.add(purchase)
        session.commit()
        other_site_id = other_site.id
        purchase_id = purchase.id

        try:
            create_supplier_bill(
                session,
                company_id=company_id,
                site_id=other_site_id,
                supplier_id=supplier_id,
                purchase_id=purchase_id,
                bill_no="INV-WRONG-SITE",
                bill_date=date(2026, 11, 22),
                due_date=None,
                currency_code="TWD",
                total_amount=Decimal("520.00"),
            )
            assert False, "帳單據點必須與關聯採購單據點一致"
        except ValueError as exc:
            assert "供應商／據點不符" in str(exc)

        session.rollback()
        assert session.query(SupplierBill).count() == 0
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()
