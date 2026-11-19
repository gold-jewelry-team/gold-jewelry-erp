from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import models
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.site import Site
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.routers import bank_accounts, bank_reconciliation

def test_statement_csv_import_duplicate_detection_and_matching():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="RECON",name="銀行對帳測試銀樓"); db.add(company); db.flush()
    account=BankAccount(company_id=company.id,bank_name="測試銀行",account_name="營運帳戶",
        account_last4="1234",currency_code="TWD",opening_balance=Decimal("0"),
        opening_balance_at=datetime.now(timezone.utc)); db.add(account); db.commit()
    cid,aid=company.id,account.id; db.close()
    def override():
        s=Session()
        try: yield s
        finally: s.close()
    app.dependency_overrides.clear()
    app.dependency_overrides[bank_accounts.get_db]=override
    app.dependency_overrides[bank_reconciliation.get_db]=override
    try:
        client=TestClient(app); root=f"/companies/{cid}/bank-accounts/{aid}"
        tx=client.post(f"/companies/{cid}/bank-accounts",json={
            "bank_name":"其他","account_name":"次帳戶","account_last4":"5678",
            "opening_balance":"0.00","opening_balance_at":datetime.now(timezone.utc).isoformat()})
        assert tx.status_code==201
        # Seed a ledger transaction in the same in-memory SQLite database.
        seed=Session()
        ledger=BankTransaction(company_id=cid,bank_account_id=aid,transaction_type="CASH_DEPOSIT",
            direction="IN",amount=Decimal("1250.00"),currency_code="TWD",
            reference_no="REF-01",description="現金存款",created_by_name="測試",
            occurred_at=datetime(2026,11,19,2,0,tzinfo=timezone.utc))
        seed.add(ledger); seed.commit(); seed.close()
        csv_text="transaction_date,description,amount,direction,reference_no\n2026-11-19,現金存款,1250.00,IN,REF-01\n2026-11-19,銀行手續費,20.00,OUT,FEE-01\n"
        imported=client.post(f"{root}/statement-imports",json={"csv_content":csv_text,"source_file_name":"nov.csv","imported_by_name":"店員甲"})
        assert imported.status_code==201,imported.text
        import_id=imported.json()["id"]
        lines=client.get(f"{root}/statement-imports/{import_id}/lines")
        assert lines.status_code==200,lines.text
        assert [x["status"] for x in lines.json()]==["MATCHED","UNMATCHED"]
        line_id=lines.json()[1]["id"]
        duplicate=client.post(f"{root}/statement-imports",json={"csv_content":csv_text,"source_file_name":"nov-copy.csv","imported_by_name":"店員甲"})
        assert duplicate.status_code==201,duplicate.text
        duplicate_lines=client.get(f"{root}/statement-imports/{duplicate.json()['id']}/lines")
        assert all(x["status"]=="DUPLICATE" for x in duplicate_lines.json())
        check=Session()
        assert check.query(BankStatementImport).count()==2
        assert check.query(BankStatementLine).count()==4
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
