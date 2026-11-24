from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.bank_account import BankAccount, BankTransaction
from app.models.company import Company
from app.routers import bank_accounts


def test_bank_balance_only_counts_transactions_at_or_after_opening_balance_time():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = TestSession()
    company = Company(code="BANK-OPENING-CUTOFF", name="銀行期初餘額時點測試")
    db.add(company)
    db.flush()

    opening_at = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="1234",
        currency_code="TWD",
        opening_balance=Decimal("10000.00"),
        opening_balance_at=opening_at,
    )
    db.add(account)
    db.flush()

    db.add_all([
        BankTransaction(
            company_id=company.id,
            bank_account_id=account.id,
            transaction_type="CASH_DEPOSIT",
            direction="IN",
            amount=Decimal("1000.00"),
            currency_code="TWD",
            description="期初時點前的歷史入帳",
            created_by_name="測試人員",
            occurred_at=opening_at - timedelta(days=1),
        ),
        BankTransaction(
            company_id=company.id,
            bank_account_id=account.id,
            transaction_type="CASH_WITHDRAWAL",
            direction="OUT",
            amount=Decimal("500.00"),
            currency_code="TWD",
            description="期初時點前的歷史出帳",
            created_by_name="測試人員",
            occurred_at=opening_at - timedelta(hours=1),
        ),
        BankTransaction(
            company_id=company.id,
            bank_account_id=account.id,
            transaction_type="INTEREST_IN",
            direction="IN",
            amount=Decimal("50.00"),
            currency_code="TWD",
            description="期初時點當下入帳",
            created_by_name="測試人員",
            occurred_at=opening_at,
        ),
        BankTransaction(
            company_id=company.id,
            bank_account_id=account.id,
            transaction_type="CASH_DEPOSIT",
            direction="IN",
            amount=Decimal("2000.00"),
            currency_code="TWD",
            description="期初時點後入帳",
            created_by_name="測試人員",
            occurred_at=opening_at + timedelta(days=1),
        ),
        BankTransaction(
            company_id=company.id,
            bank_account_id=account.id,
            transaction_type="CASH_WITHDRAWAL",
            direction="OUT",
            amount=Decimal("300.00"),
            currency_code="TWD",
            description="期初時點後出帳",
            created_by_name="測試人員",
            occurred_at=opening_at + timedelta(days=2),
        ),
    ])
    db.commit()
    company_id = company.id
    account_id = account.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[bank_accounts.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get(f"/companies/{company_id}/bank-accounts")
        assert response.status_code == 200, response.text
        row = next(
            item for item in response.json()
            if item["account"]["id"] == str(account_id)
        )
        # Old transactions remain in the ledger but are already represented
        # by the opening balance. The boundary timestamp is included.
        assert row["current_balance"] == "11750.00"

        history = client.get(
            f"/companies/{company_id}/bank-accounts/{account_id}/transactions"
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 5
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
