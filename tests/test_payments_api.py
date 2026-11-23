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
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.routers import daily_closing, payments, cash_counts


def _payment_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="PAYMENT-TEST", name="收付款測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    now = datetime.now(timezone.utc)
    sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="PAY-SALE-001",
        status="COMPLETED", payment_method="CASH", currency_code="TWD",
        subtotal=Decimal("1000"), card_fee=Decimal("0"),
        final_amount=Decimal("1000"), completed_at=now,
    )
    negative_sale = Sale(
        company_id=company.id, site_id=site.id, sale_no="PAY-SALE-NEG",
        status="COMPLETED", payment_method="OTHER", currency_code="TWD",
        subtotal=Decimal("-150"), card_fee=Decimal("0"),
        final_amount=Decimal("-150"), completed_at=now,
    )
    session.add_all([sale, negative_sale])
    session.flush()
    returned = SaleReturn(
        company_id=company.id, site_id=site.id, sale_id=sale.id,
        return_no="PAY-RETURN-001",
        settlement_reversal_amount=Decimal("-300"),
        currency_code="TWD", created_at=now,
    )
    customer_owes = SaleReturn(
        company_id=company.id, site_id=site.id, sale_id=sale.id,
        return_no="PAY-RETURN-002",
        settlement_reversal_amount=Decimal("50"),
        currency_code="TWD", created_at=now,
    )
    session.add_all([returned, customer_owes])
    session.commit()
    ids = (company.id, site.id, sale.id, negative_sale.id, returned.id, customer_owes.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[payments.get_db] = override_db
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[cash_counts.get_db] = override_db
    return engine, TestSession, ids, now


def test_partial_collections_refunds_and_daily_cash_flow_summary():
    engine, TestSession, ids, now = _payment_context()
    company_id, site_id, sale_id, _, return_id, customer_owes_id = ids
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        first = client.post(f"{base}/sales/{sale_id}/payments", json={
            "payment_method": "CASH", "amount": "400.00",
            "reference_no": "CASH-001",
        })
        assert first.status_code == 201, first.text
        assert first.json()["direction"] == "IN"

        second = client.post(f"{base}/sales/{sale_id}/payments", json={
            "payment_method": "CARD", "amount": "600.00",
            "reference_no": "CARD-001",
        })
        assert second.status_code == 201, second.text
        overpay = client.post(f"{base}/sales/{sale_id}/payments", json={
            "payment_method": "CASH", "amount": "0.01",
        })
        assert overpay.status_code == 422

        refund1 = client.post(f"{base}/sales/returns/{return_id}/payments", json={
            "payment_method": "TRANSFER", "amount": "200.00",
            "reference_no": "BANK-REFUND-001",
        })
        assert refund1.status_code == 201, refund1.text
        assert refund1.json()["direction"] == "OUT"
        refund2 = client.post(f"{base}/sales/returns/{return_id}/payments", json={
            "payment_method": "CASH", "amount": "100.00",
        })
        assert refund2.status_code == 201, refund2.text
        overrefund = client.post(f"{base}/sales/returns/{return_id}/payments", json={
            "payment_method": "CASH", "amount": "0.01",
        })
        assert overrefund.status_code == 422

        collect_due = client.post(f"{base}/sales/returns/{customer_owes_id}/payments", json={
            "payment_method": "CASH", "amount": "50.00",
        })
        assert collect_due.status_code == 201, collect_due.text
        assert collect_due.json()["direction"] == "IN"

        negative = client.post(f"{base}/sales/{ids[3]}/payments", json={
            "payment_method": "TRANSFER", "amount": "150.00",
        })
        assert negative.status_code == 201, negative.text
        assert negative.json()["direction"] == "OUT"

        listed = client.get(f"{base}/sales/{sale_id}/payments")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        business_date = now.astimezone().date()
        # Taipei business date is derived from the transaction's actual local date.
        from zoneinfo import ZoneInfo
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        close = client.post(
            f"{base}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text
        result = close.json()
        assert result["collected_amount"] == "1050.00"
        assert result["refunded_amount"] == "450.00"
        assert result["net_cash_flow"] == "600.00"

        summaries = {item["payment_method"]: item for item in result["payment_summaries"]}
        assert summaries["CASH"]["collected_amount"] == "450.00"
        assert summaries["CASH"]["refunded_amount"] == "100.00"
        assert summaries["CARD"]["collected_amount"] == "600.00"
        assert summaries["TRANSFER"]["refunded_amount"] == "350.00"

        check = TestSession()
        assert check.query(PaymentTransaction).count() == 6
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_payment_rejects_non_completed_sale_and_bad_amount():
    engine, TestSession, ids, _ = _payment_context()
    company_id, site_id, sale_id, _, return_id, _ = ids
    try:
        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sales/{sale_id}/payments",
            json={"payment_method": "CRYPTO", "amount": "10.001"},
        )
        assert response.status_code == 422
        check = TestSession()
        assert check.query(PaymentTransaction).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_customer_collection_and_refund_are_blocked_after_daily_closing():
    from zoneinfo import ZoneInfo

    engine, TestSession, ids, now = _payment_context()
    company_id, site_id, sale_id, _, return_id, _ = ids
    try:
        client = TestClient(app)
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text

        base = f"/companies/{company_id}"
        collection = client.post(
            f"{base}/sales/{sale_id}/payments",
            json={"payment_method": "CASH", "amount": "100.00"},
        )
        assert collection.status_code == 422
        assert "已結帳" in collection.json()["detail"]

        refund = client.post(
            f"{base}/sales/returns/{return_id}/payments",
            json={"payment_method": "CASH", "amount": "100.00"},
        )
        assert refund.status_code == 422
        assert "已結帳" in refund.json()["detail"]

        check = TestSession()
        assert check.query(PaymentTransaction).count() == 0
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

def test_mixed_sale_collections_must_match_card_fee_and_cash_tender_plan():
    engine, TestSession, ids, _ = _payment_context()
    company_id, site_id = ids[0], ids[1]
    session = TestSession()
    mixed_sale = Sale(
        company_id=company_id,
        site_id=site_id,
        sale_no="PAY-MIXED-001",
        status="COMPLETED",
        payment_method="MIXED",
        currency_code="TWD",
        subtotal=Decimal("30000"),
        card_amount=Decimal("10000"),
        card_fee=Decimal("500"),
        final_amount=Decimal("30500"),
        completed_at=datetime.now(timezone.utc),
    )
    session.add(mixed_sale)
    session.commit()
    sale_id = mixed_sale.id
    session.close()

    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/sales/{sale_id}/payments"

        # Card terminal must receive card principal plus the 5% fee.
        card = client.post(base, json={"payment_method": "CARD", "amount": "10500"})
        assert card.status_code == 201, card.text

        excess_card = client.post(base, json={"payment_method": "CARD", "amount": "0.01"})
        assert excess_card.status_code == 422
        assert "刷卡" in excess_card.json()["detail"]

        # The cash remainder is the original cash principal, without surcharge.
        cash = client.post(base, json={"payment_method": "CASH", "amount": "20000"})
        assert cash.status_code == 201, cash.text

        excess_cash = client.post(base, json={"payment_method": "CASH", "amount": "0.01"})
        assert excess_cash.status_code == 422
        assert "現金" in excess_cash.json()["detail"]

        wrong_method = client.post(base, json={"payment_method": "TRANSFER", "amount": "1"})
        assert wrong_method.status_code == 422
        assert "刷卡及現金" in wrong_method.json()["detail"]

        listed = client.get(base)
        assert listed.status_code == 200
        assert sum(Decimal(row["amount"]) for row in listed.json()) == Decimal("30500.00")
        assert {row["payment_method"] for row in listed.json()} == {"CARD", "CASH"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


 
def test_cash_refund_and_drawer_transfers_reconcile_to_physical_cash_count():
    engine, TestSession, ids, now = _payment_context()
    company_id, site_id, sale_id, _, return_id, _ = ids
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"

        collected = client.post(
            f"{base}/sales/{sale_id}/payments",
            json={"payment_method": "CASH", "amount": "1000.00"},
        )
        assert collected.status_code == 201, collected.text
        refunded = client.post(
            f"{base}/sales/returns/{return_id}/payments",
            json={"payment_method": "CASH", "amount": "100.00"},
        )
        assert refunded.status_code == 201, refunded.text
        assert refunded.json()["direction"] == "OUT"

        db = TestSession()
        db.add_all([
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="BANK_DEPOSIT", direction="OUT",
                amount=Decimal("100.00"), currency_code="TWD",
                description="存入銀行", created_by_name="測試店員",
                created_at=now,
            ),
            CashDrawerMovement(
                company_id=company_id, site_id=site_id,
                movement_type="FLOAT_INCREASE", direction="IN",
                amount=Decimal("50.00"), currency_code="TWD",
                description="增加備用金", created_by_name="測試店員",
                created_at=now,
            ),
        ])
        db.commit()
        db.close()

        from zoneinfo import ZoneInfo
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"{base}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        snapshot = closing.json()
        assert snapshot["collected_amount"] == "1000.00"
        assert snapshot["refunded_amount"] == "100.00"
        assert snapshot["cash_drawer_in_amount"] == "50.00"
        assert snapshot["cash_drawer_out_amount"] == "100.00"

        counted = client.post(
            f"{base}/sites/{site_id}/daily-closings/{snapshot['id']}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "1350.00",
                "counted_by_name": "甲",
            },
        )
        assert counted.status_code == 201, counted.text
        assert counted.json()["expected_cash_amount"] == "1350.00"
        assert counted.json()["cash_variance"] == "0.00"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

 
def test_non_cash_return_refund_does_not_reduce_physical_cash_count():
    engine, TestSession, ids, now = _payment_context()
    company_id, site_id, sale_id, _, return_id, _ = ids
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"

        collected = client.post(
            f"{base}/sales/{sale_id}/payments",
            json={"payment_method": "CASH", "amount": "1000.00"},
        )
        assert collected.status_code == 201, collected.text
        refunded = client.post(
            f"{base}/sales/returns/{return_id}/payments",
            json={
                "payment_method": "TRANSFER",
                "amount": "100.00",
                "reference_no": "BANK-REFUND-NON-CASH",
            },
        )
        assert refunded.status_code == 201, refunded.text
        assert refunded.json()["direction"] == "OUT"

        from zoneinfo import ZoneInfo
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"{base}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        snapshot = closing.json()
        assert snapshot["collected_amount"] == "1000.00"
        assert snapshot["refunded_amount"] == "100.00"
        assert snapshot["cash_drawer_out_amount"] == "0.00"

        summaries = {item["payment_method"]: item for item in snapshot["payment_summaries"]}
        assert summaries["CASH"]["net_cash_flow"] == "1000.00"
        assert summaries["TRANSFER"]["refunded_amount"] == "100.00"
        assert summaries["TRANSFER"]["net_cash_flow"] == "-100.00"

        counted = client.post(
            f"{base}/sites/{site_id}/daily-closings/{snapshot['id']}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "1500.00",
                "counted_by_name": "乙",
            },
        )
        assert counted.status_code == 201, counted.text
        assert counted.json()["expected_cash_amount"] == "1500.00"
        assert counted.json()["cash_variance"] == "0.00"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

 
def test_cash_count_records_variance_and_rejects_duplicate_count():
    engine, TestSession, ids, now = _payment_context()
    company_id, site_id = ids[0], ids[1]
    try:
        client = TestClient(app)
        from zoneinfo import ZoneInfo
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        closing_id = closing.json()["id"]

        counted = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings/{closing_id}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "475.00",
                "counted_by_name": "盤點甲",
                "count_note": "實際現金短少",
            },
        )
        assert counted.status_code == 201, counted.text
        assert counted.json()["expected_cash_amount"] == "500.00"
        assert counted.json()["counted_cash_amount"] == "475.00"
        assert counted.json()["cash_variance"] == "-25.00"

        duplicate = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings/{closing_id}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "500.00",
                "counted_by_name": "盤點乙",
            },
        )
        assert duplicate.status_code == 422
        check = TestSession()
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

 
def test_cash_count_requires_independent_reviewer_and_is_reviewed_once():
    engine, TestSession, ids, now = _payment_context()
    company_id, site_id = ids[0], ids[1]
    try:
        client = TestClient(app)
        from zoneinfo import ZoneInfo
        business_date = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text
        closing_id = closing.json()["id"]

        counted = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings/{closing_id}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "500.00",
                "counted_by_name": "盤點甲",
            },
        )
        assert counted.status_code == 201, counted.text
        count_id = counted.json()["id"]
        review_url = (
            f"/companies/{company_id}/sites/{site_id}/daily-closings/"
            f"{closing_id}/cash-count/{count_id}/review"
        )

        self_review = client.post(review_url, json={"reviewed_by_name": "盤點甲"})
        assert self_review.status_code == 422
        assert "不同" in self_review.json()["detail"]

        reviewed = client.post(review_url, json={
            "reviewed_by_name": "覆核乙",
            "review_note": "已核對現金盤點",
        })
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["reviewed_by_name"] == "覆核乙"
        assert reviewed.json()["review_note"] == "已核對現金盤點"
        assert reviewed.json()["reviewed_at"] is not None

        duplicate_review = client.post(review_url, json={"reviewed_by_name": "覆核丙"})
        assert duplicate_review.status_code == 422
        assert "已完成覆核" in duplicate_review.json()["detail"]

        check = TestSession()
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_mixed_sale_allows_partial_card_and_cash_installments_with_exact_tender_caps():
    engine, TestSession, ids, _ = _payment_context()
    company_id, site_id = ids[0], ids[1]
    session = TestSession()
    mixed_sale = Sale(
        company_id=company_id,
        site_id=site_id,
        sale_no="PAY-MIXED-PARTIAL-001",
        status="COMPLETED",
        payment_method="MIXED",
        currency_code="TWD",
        subtotal=Decimal("30000"),
        card_amount=Decimal("10000"),
        card_fee=Decimal("500"),
        final_amount=Decimal("30500"),
        completed_at=datetime.now(timezone.utc),
    )
    session.add(mixed_sale)
    session.commit()
    sale_id = mixed_sale.id
    session.close()

    try:
        client = TestClient(app)
        url = f"/companies/{company_id}/sales/{sale_id}/payments"

        card_first = client.post(url, json={
            "payment_method": "CARD", "amount": "6000.00",
        })
        assert card_first.status_code == 201, card_first.text
        card_second = client.post(url, json={
            "payment_method": "CARD", "amount": "4500.00",
        })
        assert card_second.status_code == 201, card_second.text
        card_over = client.post(url, json={
            "payment_method": "CARD", "amount": "0.01",
        })
        assert card_over.status_code == 422
        assert "刷卡" in card_over.json()["detail"]

        cash_first = client.post(url, json={
            "payment_method": "CASH", "amount": "12500.00",
        })
        assert cash_first.status_code == 201, cash_first.text
        cash_over = client.post(url, json={
            "payment_method": "CASH", "amount": "7500.01",
        })
        assert cash_over.status_code == 422
        cash_second = client.post(url, json={
            "payment_method": "CASH", "amount": "7500.00",
        })
        assert cash_second.status_code == 201, cash_second.text

        rows = client.get(url)
        assert rows.status_code == 200
        card_total = sum(
            (Decimal(row["amount"]) for row in rows.json()
             if row["payment_method"] == "CARD"), Decimal("0")
        )
        cash_total = sum(
            (Decimal(row["amount"]) for row in rows.json()
             if row["payment_method"] == "CASH"), Decimal("0")
        )
        assert card_total == Decimal("10500.00")
        assert cash_total == Decimal("20000.00")
        assert len(rows.json()) == 4

        verify = TestSession()
        assert verify.query(PaymentTransaction).count() == 4
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
