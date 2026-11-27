from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankAccount, BankTransaction
from app.models.company import Company
from app.models.operating_expense import OperatingExpense
from app.models.payment_transaction import PaymentTransaction
from app.models.sale import Sale
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierPayment
from app.routers import bank_accounts


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BANK-TRANSFER-LINK", name="銀行轉帳連結測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP01", name="測試供應商")
    db.add_all([site, supplier])
    db.flush()

    now = datetime.now(timezone.utc)
    sale = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="SO-TRANSFER-LINK-001",
        status="COMPLETED",
        payment_method="TRANSFER",
        currency_code="TWD",
        subtotal=Decimal("100.00"),
        card_amount=Decimal("0.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("100.00"),
        completed_at=now,
    )
    old_sale = Sale(
        company_id=company.id,
        site_id=site.id,
        sale_no="SO-TRANSFER-LINK-OLD",
        status="COMPLETED",
        payment_method="TRANSFER",
        currency_code="TWD",
        subtotal=Decimal("40.00"),
        card_amount=Decimal("0.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("40.00"),
        completed_at=now - timedelta(days=3),
    )
    db.add_all([sale, old_sale])
    db.flush()

    payment = PaymentTransaction(
        company_id=company.id,
        site_id=site.id,
        sale_id=sale.id,
        direction="IN",
        payment_method="TRANSFER",
        amount=Decimal("100.00"),
        currency_code="TWD",
        reference_no="CUST-TR-001",
        paid_at=now,
        note="客戶匯款",
    )
    old_payment = PaymentTransaction(
        company_id=company.id,
        site_id=site.id,
        sale_id=old_sale.id,
        direction="IN",
        payment_method="TRANSFER",
        amount=Decimal("40.00"),
        currency_code="TWD",
        reference_no="CUST-TR-OLD",
        paid_at=now - timedelta(days=3),
    )
    supplier_payment = SupplierPayment(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        payment_no="SP-TRANSFER-001",
        payment_method="TRANSFER",
        total_amount=Decimal("200.00"),
        currency_code="TWD",
        reference_no="SUP-TR-001",
        paid_at=now,
    )
    expense = OperatingExpense(
        company_id=company.id,
        site_id=site.id,
        expense_no="EX-TRANSFER-001",
        expense_date=now.date(),
        category_code="OTHER",
        description="測試轉帳費用",
        payee="測試廠商",
        amount=Decimal("50.00"),
        currency_code="TWD",
        status="PAID",
        payment_method="TRANSFER",
        paid_at=now,
        receipt_no="EXP-TR-001",
    )
    db.add_all([payment, old_payment, supplier_payment, expense])
    db.commit()
    ids = {
        "company_id": company.id,
        "site_id": site.id,
        "payment_id": payment.id,
        "old_payment_id": old_payment.id,
        "supplier_payment_id": supplier_payment.id,
        "expense_id": expense.id,
    }
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[bank_accounts.get_db] = override_db
    return engine, TestSession, ids


def _create_account(client, company_id, name, opening_at):
    response = client.post(
        f"/companies/{company_id}/bank-accounts",
        json={
            "bank_name": "測試銀行",
            "account_name": name,
            "account_last4": "1234" if name == "營運帳戶" else "5678",
            "opening_balance": "1000.00",
            "opening_balance_at": opening_at.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_transfer_payments_can_be_linked_once_to_the_correct_bank_account():
    engine, TestSession, ids = _context()
    try:
        client = TestClient(app)
        company_id = ids["company_id"]
        base = f"/companies/{company_id}/bank-accounts"
        now = datetime.now(timezone.utc)
        account_id = _create_account(
            client, company_id, "營運帳戶", now - timedelta(days=2)
        )
        other_account_id = _create_account(
            client, company_id, "備用帳戶", now - timedelta(days=2)
        )

        pending = client.get(f"{base}/pending-transfers")
        assert pending.status_code == 200, pending.text
        assert len(pending.json()) == 4
        pending_types = {row["source_type"] for row in pending.json()}
        assert pending_types == {
            "PAYMENT_TRANSACTION", "SUPPLIER_PAYMENT", "OPERATING_EXPENSE"
        }

        sources = [
            ("PAYMENT_TRANSACTION", ids["payment_id"], "IN", "100.00"),
            ("SUPPLIER_PAYMENT", ids["supplier_payment_id"], "OUT", "200.00"),
            ("OPERATING_EXPENSE", ids["expense_id"], "OUT", "50.00"),
        ]
        linked_ids = []
        for source_type, source_id, direction, amount in sources:
            linked = client.post(
                f"{base}/{account_id}/transfer-links",
                json={
                    "source_type": source_type,
                    "source_id": str(source_id),
                    "created_by_name": "測試管理者",
                },
            )
            assert linked.status_code == 201, linked.text
            row = linked.json()
            assert row["direction"] == direction
            assert row["amount"] == amount
            assert row["bank_account_id"] == account_id
            assert row["source_type"] == source_type
            assert row["source_id"] == str(source_id)
            assert row["transaction_type"] == (
                "TRANSFER_IN" if direction == "IN" else "TRANSFER_OUT"
            )
            linked_ids.append(row["id"])

        retry = client.post(
            f"{base}/{account_id}/transfer-links",
            json={
                "source_type": "PAYMENT_TRANSACTION",
                "source_id": str(ids["payment_id"]),
                "created_by_name": "測試管理者",
            },
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["id"] == linked_ids[0]

        wrong_account = client.post(
            f"{base}/{other_account_id}/transfer-links",
            json={
                "source_type": "PAYMENT_TRANSACTION",
                "source_id": str(ids["payment_id"]),
                "created_by_name": "測試管理者",
            },
        )
        assert wrong_account.status_code == 409, wrong_account.text

        refreshed_pending = client.get(f"{base}/pending-transfers")
        assert refreshed_pending.status_code == 200
        assert len(refreshed_pending.json()) == 1
        assert refreshed_pending.json()[0]["source_id"] == str(ids["old_payment_id"])

        accounts = client.get(base)
        assert accounts.status_code == 200, accounts.text
        balance = next(
            item["current_balance"]
            for item in accounts.json()
            if item["account"]["id"] == account_id
        )
        assert balance == "850.00"

        check = TestSession()
        assert check.query(BankTransaction).count() == 3
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_transfer_older_than_account_opening_balance_is_not_linked():
    engine, TestSession, ids = _context()
    try:
        client = TestClient(app)
        company_id = ids["company_id"]
        base = f"/companies/{company_id}/bank-accounts"
        account_id = _create_account(
            client,
            company_id,
            "營運帳戶",
            datetime.now(timezone.utc) - timedelta(days=1),
        )
        response = client.post(
            f"{base}/{account_id}/transfer-links",
            json={
                "source_type": "PAYMENT_TRANSACTION",
                "source_id": str(ids["old_payment_id"]),
                "created_by_name": "測試管理者",
            },
        )
        assert response.status_code == 422, response.text
        assert "早於" in response.json()["detail"]
        check = TestSession()
        assert check.query(BankTransaction).count() == 0
        check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()



def test_transfer_source_module_permissions_are_enforced(monkeypatch):
    engine, _TestSession, ids = _context()
    try:
        client = TestClient(app)
        company_id = ids["company_id"]
        base = f"/companies/{company_id}/bank-accounts"
        account_id = _create_account(
            client, company_id, "權限測試帳戶", datetime.now(timezone.utc) - timedelta(days=2)
        )

        def allow_only_payment_view(_db, permission_code):
            if permission_code != "payments.view":
                raise HTTPException(status_code=403, detail=f"需要 {permission_code}")

        monkeypatch.setattr(
            bank_accounts, "require_current_actor_permission", allow_only_payment_view
        )

        pending = client.get(f"{base}/pending-transfers")
        assert pending.status_code == 200, pending.text
        assert pending.json()
        assert {row["source_type"] for row in pending.json()} == {"PAYMENT_TRANSACTION"}

        denied = client.post(
            f"{base}/{account_id}/transfer-links",
            json={
                "source_type": "SUPPLIER_PAYMENT",
                "source_id": str(ids["supplier_payment_id"]),
                "created_by_name": "測試成員",
            },
        )
        assert denied.status_code == 403, denied.text

        allowed = client.post(
            f"{base}/{account_id}/transfer-links",
            json={
                "source_type": "PAYMENT_TRANSACTION",
                "source_id": str(ids["payment_id"]),
                "created_by_name": "測試成員",
            },
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
