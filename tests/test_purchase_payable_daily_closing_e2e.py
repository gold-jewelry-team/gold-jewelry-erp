from datetime import datetime, timezone
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
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier_payable import SupplierBill, SupplierPayment
from app.routers import daily_closing, purchases, supplier_payables, suppliers
from app.services.inventory import get_stock_balance


def test_purchase_receipt_supplier_bill_partial_payments_and_daily_close_e2e():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PURCHASE-PAYABLE-E2E", name="採購應付日結整合測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id,
        product_code="PURCHASE-PAYABLE-E2E-001",
        barcode="PURCHASE-PAYABLE-E2E-BAR-001",
        name="整合測試黃金戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    db.add_all([location, product])
    db.commit()
    company_id, site_id, location_id, product_id = (
        company.id, site.id, location.id, product.id
    )
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    dependencies = (
        suppliers.get_db,
        purchases.get_db,
        supplier_payables.get_db,
        daily_closing.get_db,
    )
    app.dependency_overrides.clear()
    for dependency in dependencies:
        app.dependency_overrides[dependency] = override_db
    try:
        client = TestClient(app)
        supplier_response = client.post(
            f"/companies/{company_id}/suppliers",
            json={"code": "SUP-E2E", "name": "整合測試供應商"},
        )
        assert supplier_response.status_code == 201, supplier_response.text
        supplier_id = supplier_response.json()["id"]

        purchase_response = client.post(
            f"/companies/{company_id}/purchases",
            json={
                "site_id": str(site_id),
                "supplier_id": supplier_id,
                "purchase_no": "PO-PAYABLE-E2E-001",
                "order_date": "2026-11-23",
                "currency_code": "TWD",
                "lines": [{
                    "product_id": str(product_id),
                    "quantity": "1",
                    "weight": "1.0000",
                    "weight_unit_code": "QIAN",
                    "unit_cost": "12000.00",
                    "cost_labor_fee": "350.00",
                }],
            },
        )
        assert purchase_response.status_code == 201, purchase_response.text
        purchase = purchase_response.json()
        submitted = client.post(
            f"/companies/{company_id}/purchases/{purchase['id']}/submit"
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "ORDERED"

        receipt = client.post(
            f"/companies/{company_id}/purchases/{purchase['id']}/receive",
            json={
                "purchase_line_id": purchase["lines"][0]["id"],
                "location_id": str(location_id),
                "received_quantity": "1",
            },
        )
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["status"] == "RECEIVED"

        payable_base = f"/companies/{company_id}/supplier-payables"
        bill_response = client.post(f"{payable_base}/bills", json={
            "site_id": str(site_id),
            "supplier_id": supplier_id,
            "purchase_id": purchase["id"],
            "bill_no": "INV-PAYABLE-E2E-001",
            "bill_date": "2026-11-23",
            "currency_code": "TWD",
            "total_amount": "12350.00",
        })
        assert bill_response.status_code == 201, bill_response.text
        bill = bill_response.json()
        assert bill["purchase_id"] == purchase["id"]
        assert bill["status"] == "OPEN"

        first_payment = client.post(f"{payable_base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": supplier_id,
            "payment_no": "SP-PAYABLE-E2E-001",
            "payment_method": "TRANSFER",
            "allocations": [{"bill_id": bill["id"], "amount": "5000.00"}],
        })
        assert first_payment.status_code == 201, first_payment.text
        after_first = client.get(f"{payable_base}/bills/{bill['id']}")
        assert after_first.json()["status"] == "PARTIALLY_PAID"
        assert after_first.json()["paid_amount"] == "5000.00"
        assert after_first.json()["outstanding_amount"] == "7350.00"

        second_payment = client.post(f"{payable_base}/payments", json={
            "site_id": str(site_id),
            "supplier_id": supplier_id,
            "payment_no": "SP-PAYABLE-E2E-002",
            "payment_method": "CASH",
            "allocations": [{"bill_id": bill["id"], "amount": "7350.00"}],
        })
        assert second_payment.status_code == 201, second_payment.text
        settled = client.get(f"{payable_base}/bills/{bill['id']}")
        assert settled.json()["status"] == "PAID"
        assert settled.json()["paid_amount"] == "12350.00"
        assert settled.json()["outstanding_amount"] == "0.00"

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        assert closing.json()["supplier_paid_amount"] == "12350.00"
        assert closing.json()["net_cash_flow"] == "-12350.00"
        summaries = {
            item["payment_method"]: item
            for item in closing.json()["payment_summaries"]
        }
        assert summaries["TRANSFER"]["supplier_paid_amount"] == "5000.00"
        assert summaries["CASH"]["supplier_paid_amount"] == "7350.00"

        verify = TestSession()
        persisted_purchase = verify.get(Purchase, purchase["id"])
        assert persisted_purchase.status == "RECEIVED"
        assert verify.query(SupplierBill).count() == 1
        assert verify.query(SupplierPayment).count() == 2
        assert verify.query(InventoryMovement).filter_by(
            reference_type="PURCHASE_LINE"
        ).count() == 1
        assert get_stock_balance(
            verify, product_id=product_id, location_id=location_id
        ) == Decimal("1")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
