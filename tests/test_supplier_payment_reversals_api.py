from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.daily_closing import DailyClosing
from app.models.supplier_payable import (
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierPaymentReversal,
)
from app.models.company import Company
from app.models.site import Site
from app.models.supplier import Supplier
from app.routers import bank_accounts, daily_closing, supplier_payables


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        company = Company(code="SUP-REVERSAL", name="付款沖銷測試公司")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-REV", name="沖銷測試供應商")
        db.add_all([site, supplier])
        db.commit()
        ids = (company.id, site.id, supplier.id)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[supplier_payables.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[bank_accounts.get_db] = override_db
    return engine, Session, ids


def _bill_and_payment(client, company_id, site_id, supplier_id):
    base = f"/companies/{company_id}/supplier-payables"
    bill = client.post(f"{base}/bills", json={
        "site_id": str(site_id),
        "supplier_id": str(supplier_id),
        "bill_no": "INV-REVERSAL-001",
        "bill_date": date.today().isoformat(),
        "currency_code": "TWD",
        "total_amount": "1000.00",
    })
    assert bill.status_code == 201, bill.text
    payment = client.post(f"{base}/payments", json={
        "site_id": str(site_id),
        "supplier_id": str(supplier_id),
        "payment_no": "SP-REVERSAL-001",
        "payment_method": "TRANSFER",
        "allocations": [{"bill_id": bill.json()["id"], "amount": "1000.00"}],
    })
    assert payment.status_code == 201, payment.text
    return base, bill.json(), payment.json()


def test_partial_and_full_supplier_payment_reversal_restores_balance_and_preserves_history():
    engine, Session, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        base, bill, payment = _bill_and_payment(client, company_id, site_id, supplier_id)
        allocation_id = payment["allocations"][0]["id"]

        partial = client.post(f"{base}/payments/{payment['id']}/reverse", json={
            "reversal_no": "SPR-REV-001",
            "reason": "供應商退回部分款項",
            "allocations": [{"payment_allocation_id": allocation_id, "amount": "300.00"}],
        })
        assert partial.status_code == 201, partial.text
        part_bill = client.get(f"{base}/bills/{bill['id']}").json()
        assert (
            part_bill["status"],
            part_bill["paid_amount"],
            part_bill["outstanding_amount"],
        ) == ("PARTIALLY_PAID", "700.00", "300.00")

        replay = client.post(f"{base}/payments/{payment['id']}/reverse", json={
            "reversal_no": "SPR-REV-001",
            "reason": "供應商退回部分款項",
            "allocations": [{"payment_allocation_id": allocation_id, "amount": "300.00"}],
        })
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == partial.json()["id"]

        over = client.post(f"{base}/payments/{payment['id']}/reverse", json={
            "reversal_no": "SPR-REV-002",
            "reason": "超額沖銷",
            "allocations": [{"payment_allocation_id": allocation_id, "amount": "700.01"}],
        })
        assert over.status_code == 422, over.text

        remaining = client.post(f"{base}/payments/{payment['id']}/reverse", json={
            "reversal_no": "SPR-REV-002",
            "reason": "其餘款項全數退回",
            "allocations": [{"payment_allocation_id": allocation_id, "amount": "700.00"}],
        })
        assert remaining.status_code == 201, remaining.text

        open_bill = client.get(f"{base}/bills/{bill['id']}").json()
        assert (
            open_bill["status"],
            open_bill["paid_amount"],
            open_bill["outstanding_amount"],
        ) == ("OPEN", "0.00", "1000.00")

        original_payment = client.get(f"{base}/payments/{payment['id']}").json()
        assert original_payment["status"] == "REVERSED"
        assert original_payment["reversed_amount"] == "1000.00"
        assert original_payment["reversible_amount"] == "0.00"
        assert len(client.get(f"{base}/payments/{payment['id']}/reversals").json()) == 2

        # A bill reopened by a reversal must accept a new payment and calculate
        # the outstanding balance from net paid allocations, not gross history.
        new_payment = client.post(f"{base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-REVERSAL-002",
            "payment_method": "TRANSFER",
            "allocations": [{"bill_id": bill["id"], "amount": "400.00"}],
        })
        assert new_payment.status_code == 201, new_payment.text
        refreshed = client.get(f"{base}/bills/{bill['id']}").json()
        assert (
            refreshed["status"],
            refreshed["paid_amount"],
            refreshed["outstanding_amount"],
        ) == ("PARTIALLY_PAID", "400.00", "600.00")

        business_date = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        assert closing.json()["supplier_paid_amount"] == "1400.00"
        assert closing.json()["supplier_payment_reversed_amount"] == "1000.00"
        assert closing.json()["net_cash_flow"] == "-400.00"

        with Session() as db:
            assert db.query(SupplierPayment).count() == 2
            assert db.query(SupplierPaymentAllocation).count() == 2
            assert db.query(SupplierPaymentReversal).count() == 2
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_supplier_payment_reversal_is_blocked_after_daily_close():
    engine, Session, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        base, bill, payment = _bill_and_payment(client, company_id, site_id, supplier_id)
        business_date = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
        with Session() as db:
            db.add(DailyClosing(
                company_id=company_id,
                site_id=site_id,
                business_date=business_date,
                currency_code="TWD",
            ))
            db.commit()

        rejected = client.post(f"{base}/payments/{payment['id']}/reverse", json={
            "reversal_no": "SPR-CLOSED-001",
            "reason": "結帳後嘗試沖銷",
            "allocations": [{
                "payment_allocation_id": payment["allocations"][0]["id"],
                "amount": "100.00",
            }],
        })
        assert rejected.status_code == 422, rejected.text
        assert client.get(f"{base}/bills/{bill['id']}").json()["paid_amount"] == "1000.00"
        with Session() as db:
            assert db.query(SupplierPaymentReversal).count() == 0
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_supplier_payment_reversal_number_replay_conflict_is_rejected():
    engine, Session, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        base, _bill, payment = _bill_and_payment(client, company_id, site_id, supplier_id)
        allocation_id = payment["allocations"][0]["id"]
        payload = {
            "reversal_no": "SPR-CONFLICT-001",
            "reason": "原始沖銷原因",
            "allocations": [{"payment_allocation_id": allocation_id, "amount": "100.00"}],
        }
        first = client.post(f"{base}/payments/{payment['id']}/reverse", json=payload)
        conflict = client.post(
            f"{base}/payments/{payment['id']}/reverse",
            json={**payload, "reason": "不同原因"},
        )
        assert first.status_code == 201, first.text
        assert conflict.status_code == 409, conflict.text
        with Session() as db:
            assert db.query(SupplierPaymentReversal).count() == 1
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_supplier_payment_reversal_can_be_linked_as_incoming_bank_transfer():
    engine, _Session, (company_id, site_id, supplier_id) = _context()
    try:
        client = TestClient(app)
        base, _bill, payment = _bill_and_payment(client, company_id, site_id, supplier_id)
        reversal = client.post(f"{base}/payments/{payment['id']}/reverse", json={
            "reversal_no": "SPR-BANK-001",
            "reason": "銀行退匯",
            "allocations": [{
                "payment_allocation_id": payment["allocations"][0]["id"],
                "amount": "1000.00",
            }],
        })
        assert reversal.status_code == 201, reversal.text

        account = client.post(f"/companies/{company_id}/bank-accounts", json={
            "bank_name": "測試銀行",
            "account_name": "營運帳戶",
            "account_last4": "1234",
            "opening_balance": "10000.00",
            "opening_balance_at": "2026-01-01T00:00:00+00:00",
        })
        assert account.status_code == 201, account.text

        pending = client.get(f"/companies/{company_id}/bank-accounts/pending-transfers")
        assert pending.status_code == 200, pending.text
        source = next(
            row for row in pending.json()
            if row["source_type"] == "SUPPLIER_PAYMENT_REVERSAL"
        )
        assert (source["direction"], source["amount"]) == ("IN", "1000.00")

        linked = client.post(
            f"/companies/{company_id}/bank-accounts/{account.json()['id']}/transfer-links",
            json={
                "source_type": "SUPPLIER_PAYMENT_REVERSAL",
                "source_id": reversal.json()["id"],
                "created_by_name": "測試管理者",
            },
        )
        assert linked.status_code == 201, linked.text
        assert (linked.json()["direction"], linked.json()["source_type"]) == (
            "IN",
            "SUPPLIER_PAYMENT_REVERSAL",
        )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
