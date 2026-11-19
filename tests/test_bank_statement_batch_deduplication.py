from datetime import date, datetime, timezone
import hashlib
import pytest
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db.base import Base
from app.models.company import Company
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.services.bank_reconciliation import import_bank_statement_csv


def _setup():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    company = Company(code="BATCH", name="同批次重複匯入測試")
    db.add(company)
    db.flush()
    account = BankAccount(
        company_id=company.id,
        bank_name="測試銀行",
        account_name="營運帳戶",
        account_last4="1234",
        currency_code="TWD",
        opening_balance=Decimal("1000.00"),
        opening_balance_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    db.add(account)
    db.flush()
    transaction = BankTransaction(
        company_id=company.id,
        bank_account_id=account.id,
        transaction_type="INTEREST_IN",
        direction="IN",
        amount=Decimal("5.00"),
        currency_code="TWD",
        reference_no="INT-001",
        description="活存利息",
        created_by_name="測試",
        occurred_at=datetime(2026, 11, 19, 3, tzinfo=timezone.utc),
    )
    db.add(transaction)
    db.commit()
    return engine, db, company, account, transaction


def test_import_marks_repeated_rows_in_same_csv_as_duplicate_and_matches_once():
    engine, db, company, account, transaction = _setup()
    csv_content = (
        "transaction_date,description,amount,direction,reference_no\n"
        "2026-11-19,活存利息,5.00,IN,INT-001\n"
        "2026-11-19,活存利息,5.00,IN,INT-001\n"
    )

    batch = import_bank_statement_csv(
        db,
        company_id=company.id,
        bank_account_id=account.id,
        csv_content=csv_content,
        source_file_name="same-batch.csv",
        imported_by_name="測試人員",
    )
    db.commit()

    lines = list(db.scalars(
        select(BankStatementLine).where(BankStatementLine.import_id == batch.id)
    ).all())
    assert len(lines) == 2
    matched = [line for line in lines if line.status == "MATCHED"]
    duplicates = [line for line in lines if line.status == "DUPLICATE"]
    assert len(matched) == 1
    assert len(duplicates) == 1
    assert matched[0].matched_bank_transaction_id == transaction.id
    assert duplicates[0].duplicate_of_line_id == matched[0].id

    # A later import must also handle multiple historical rows with this fingerprint.
    next_batch = import_bank_statement_csv(
        db,
        company_id=company.id,
        bank_account_id=account.id,
        csv_content=csv_content.splitlines()[0] + "\n" + csv_content.splitlines()[1] + "\n",
        source_file_name="later-import.csv",
        imported_by_name="測試人員",
    )
    db.commit()
    later_line = db.scalar(
        select(BankStatementLine).where(BankStatementLine.import_id == next_batch.id)
    )
    assert later_line is not None
    assert later_line.status == "DUPLICATE"
    assert later_line.duplicate_of_line_id is not None
    engine.dispose()


def test_new_duplicates_always_reference_original_root_even_when_history_is_chained():
    engine, db, company, account, _ = _setup()
    batch = BankStatementImport(
        company_id=company.id,
        bank_account_id=account.id,
        source_file_name="historical.csv",
        row_count=3,
        status="IMPORTED",
        imported_by_name="測試人員",
    )
    db.add(batch)
    db.flush()

    root = BankStatementLine(
        import_id=batch.id,
        company_id=company.id,
        bank_account_id=account.id,
        transaction_date=date(2026, 11, 19),
        description="歷史利息",
        amount=Decimal("5.00"),
        direction="IN",
        reference_no="ROOT-001",
        fingerprint=hashlib.sha256("2026-11-19|歷史利息|5.00|IN|ROOT-001".encode("utf-8")).hexdigest(),
        status="UNMATCHED",
    )
    db.add(root)
    db.flush()

    duplicate = BankStatementLine(
        import_id=batch.id,
        company_id=company.id,
        bank_account_id=account.id,
        transaction_date=root.transaction_date,
        description=root.description,
        amount=root.amount,
        direction=root.direction,
        reference_no=root.reference_no,
        fingerprint=root.fingerprint,
        status="DUPLICATE",
        duplicate_of_line_id=root.id,
    )
    db.add(duplicate)
    db.flush()

    chained_duplicate = BankStatementLine(
        import_id=batch.id,
        company_id=company.id,
        bank_account_id=account.id,
        transaction_date=root.transaction_date,
        description=root.description,
        amount=root.amount,
        direction=root.direction,
        reference_no=root.reference_no,
        fingerprint=root.fingerprint,
        status="DUPLICATE",
        duplicate_of_line_id=duplicate.id,
    )
    db.add(chained_duplicate)
    db.commit()

    csv_content = (
        "transaction_date,description,amount,direction,reference_no\n"
        "2026-11-19,歷史利息,5.00,IN,ROOT-001\n"
        "2026-11-19,歷史利息,5.00,IN,ROOT-001\n"
    )
    imported = import_bank_statement_csv(
        db,
        company_id=company.id,
        bank_account_id=account.id,
        csv_content=csv_content,
        source_file_name="root-resolution.csv",
        imported_by_name="測試人員",
    )
    db.commit()

    imported_lines = list(db.scalars(
        select(BankStatementLine).where(BankStatementLine.import_id == imported.id)
    ).all())
    assert len(imported_lines) == 2
    assert all(line.status == "DUPLICATE" for line in imported_lines)
    assert all(line.duplicate_of_line_id == root.id for line in imported_lines)
    engine.dispose()



def test_import_rejects_historical_duplicate_cycle():
    engine, db, company, account, _ = _setup()
    batch = BankStatementImport(
        company_id=company.id,
        bank_account_id=account.id,
        source_file_name="cyclic-history.csv",
        row_count=2,
        status="IMPORTED",
        imported_by_name="測試人員",
    )
    db.add(batch)
    db.flush()

    fingerprint = hashlib.sha256(
        "2026-11-19|循環測試|8.00|IN|CYCLE-001".encode("utf-8")
    ).hexdigest()
    root = BankStatementLine(
        import_id=batch.id,
        company_id=company.id,
        bank_account_id=account.id,
        transaction_date=date(2026, 11, 19),
        description="循環測試",
        amount=Decimal("8.00"),
        direction="IN",
        reference_no="CYCLE-001",
        fingerprint=fingerprint,
        status="DUPLICATE",
    )
    db.add(root)
    db.flush()

    duplicate = BankStatementLine(
        import_id=batch.id,
        company_id=company.id,
        bank_account_id=account.id,
        transaction_date=root.transaction_date,
        description=root.description,
        amount=root.amount,
        direction=root.direction,
        reference_no=root.reference_no,
        fingerprint=root.fingerprint,
        status="DUPLICATE",
        duplicate_of_line_id=root.id,
    )
    db.add(duplicate)
    db.flush()

    # Deliberately corrupt the historical graph into a two-node cycle.
    root.duplicate_of_line_id = duplicate.id
    db.commit()

    csv_content = (
        "transaction_date,description,amount,direction,reference_no\n"
        "2026-11-19,循環測試,8.00,IN,CYCLE-001\n"
    )
    with pytest.raises(ValueError, match="歷史對帳單重複關聯存在循環"):
        import_bank_statement_csv(
            db,
            company_id=company.id,
            bank_account_id=account.id,
            csv_content=csv_content,
            source_file_name="cycle-rejection.csv",
            imported_by_name="測試人員",
        )
    db.rollback()
    engine.dispose()



@pytest.mark.parametrize("scope", ["company", "bank_account"])
def test_import_rejects_duplicate_links_outside_company_or_account_scope(scope):
    engine, db, company, account, _ = _setup()

    if scope == "company":
        foreign_company = Company(code="OTHER", name="另一家公司")
        db.add(foreign_company)
        db.flush()
        foreign_account_company_id = foreign_company.id
    else:
        foreign_account_company_id = company.id

    foreign_account = BankAccount(
        company_id=foreign_account_company_id,
        bank_name="其他銀行",
        account_name="其他帳戶",
        account_last4="5678",
        currency_code="TWD",
        opening_balance=Decimal("0.00"),
        opening_balance_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    db.add(foreign_account)
    db.flush()

    fingerprint = hashlib.sha256(
        "2026-11-19|跨範圍測試|9.00|IN|SCOPE-001".encode("utf-8")
    ).hexdigest()

    foreign_batch = BankStatementImport(
        company_id=foreign_account_company_id,
        bank_account_id=foreign_account.id,
        source_file_name="foreign.csv",
        row_count=1,
        status="IMPORTED",
        imported_by_name="測試人員",
    )
    target_batch = BankStatementImport(
        company_id=company.id,
        bank_account_id=account.id,
        source_file_name="target.csv",
        row_count=1,
        status="IMPORTED",
        imported_by_name="測試人員",
    )
    db.add_all([foreign_batch, target_batch])
    db.flush()

    foreign_root = BankStatementLine(
        import_id=foreign_batch.id,
        company_id=foreign_account_company_id,
        bank_account_id=foreign_account.id,
        transaction_date=date(2026, 11, 19),
        description="跨範圍測試",
        amount=Decimal("9.00"),
        direction="IN",
        reference_no="SCOPE-001",
        fingerprint=fingerprint,
        status="UNMATCHED",
    )
    db.add(foreign_root)
    db.flush()

    # Simulate corrupted historical data: a line in the requested account
    # points to a root owned by another account or another company.
    malformed_duplicate = BankStatementLine(
        import_id=target_batch.id,
        company_id=company.id,
        bank_account_id=account.id,
        transaction_date=date(2026, 11, 19),
        description="跨範圍測試",
        amount=Decimal("9.00"),
        direction="IN",
        reference_no="SCOPE-001",
        fingerprint=fingerprint,
        status="DUPLICATE",
        duplicate_of_line_id=foreign_root.id,
    )
    db.add(malformed_duplicate)
    db.commit()

    csv_content = (
        "transaction_date,description,amount,direction,reference_no\n"
        "2026-11-19,跨範圍測試,9.00,IN,SCOPE-001\n"
    )
    with pytest.raises(ValueError, match="跨越公司或銀行帳戶"):
        import_bank_statement_csv(
            db,
            company_id=company.id,
            bank_account_id=account.id,
            csv_content=csv_content,
            source_file_name="scope-check.csv",
            imported_by_name="測試人員",
        )
    db.rollback()
    engine.dispose()
