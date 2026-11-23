from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models.supplier_payable import SupplierPaymentAllocation


def test_supplier_payment_replay_returns_original_after_bill_paid_and_day_closed():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        bill = client.post(f"{base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-SUPPLIER-RETRY-001",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "650.00",
        })
        assert bill.status_code == 201, bill.text

        payload = {
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-RETRY-001",
            "payment_method": "TRANSFER",
            "reference_no": "BANK-RETRY-001",
            "note": "同一筆供應商付款重送",
            "allocations": [{"bill_id": bill.json()["id"], "amount": "650.00"}],
        }
        first = client.post(f"{base}/payments", json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["total_amount"] == "650.00"
        assert len(first.json()["allocations"]) == 1

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text

        # The browser may retry after the payment was committed and the business
        # day was closed. An identical request must return the original payment.
        replay = client.post(f"{base}/payments", json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["payment_no"] == payload["payment_no"]
        assert replay.json()["total_amount"] == "650.00"
        assert len(replay.json()["allocations"]) == 1

        verify = TestSession()
        payments = verify.query(SupplierPayment).filter(
            SupplierPayment.company_id == company_id
        ).all()
        allocations = verify.query(SupplierPaymentAllocation).all()
        refreshed_bill = client.get(f"{base}/bills/{bill.json()['id']}")
        assert len(payments) == 1
        assert len(allocations) == 1
        assert refreshed_bill.status_code == 200, refreshed_bill.text
        assert refreshed_bill.json()["status"] == "PAID"
        assert Decimal(refreshed_bill.json()["paid_amount"]) == Decimal("650.00")
        assert Decimal(refreshed_bill.json()["outstanding_amount"]) == Decimal("0.00")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_payment_number_reuse_with_changed_amount_is_rejected_atomically():
    engine, TestSession, (company_id, site_id, supplier_id) = _payable_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/supplier-payables"
        bill = client.post(f"{base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "bill_no": "INV-SUPPLIER-RETRY-002",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "500.00",
        })
        assert bill.status_code == 201, bill.text

        payload = {
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "payment_no": "SP-RETRY-CONFLICT",
            "payment_method": "CASH",
            "allocations": [{"bill_id": bill.json()["id"], "amount": "100.00"}],
        }
        first = client.post(f"{base}/payments", json=payload)
        changed = {
            **payload,
            "allocations": [{"bill_id": bill.json()["id"], "amount": "120.00"}],
        }
        conflict = client.post(f"{base}/payments", json=changed)

        assert first.status_code == 201, first.text
        assert conflict.status_code == 409, conflict.text
        assert "付款單號已用於不同的付款內容" in conflict.json()["detail"]

        refreshed = client.get(f"{base}/bills/{bill.json()['id']}")
        assert refreshed.status_code == 200, refreshed.text
        assert Decimal(refreshed.json()["paid_amount"]) == Decimal("100.00")
        assert Decimal(refreshed.json()["outstanding_amount"]) == Decimal("400.00")

        verify = TestSession()
        payment_count = verify.scalar(
            select(func.count()).select_from(SupplierPayment).where(
                SupplierPayment.company_id == company_id
            )
        )
        allocation_count = verify.scalar(
            select(func.count()).select_from(SupplierPaymentAllocation)
        )
        assert payment_count == 1
        assert allocation_count == 1
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
