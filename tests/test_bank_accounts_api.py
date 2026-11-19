from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
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
from app.models.cash_drawer_movement import CashDrawerMovement
from app.routers import bank_accounts, daily_closing, cash_counts, cash_drawer_movements

def test_bank_account_deposit_withdrawal_transfer_and_atomic_cash_links():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="BANKTEST",name="銀行帳戶測試銀樓"); db.add(company); db.flush()
    site=Site(company_id=company.id,code="MAIN",name="總店"); db.add(site); db.commit()
    cid,sid=company.id,site.id; db.close()
    def override():
        s=Session()
        try: yield s
        finally: s.close()
    app.dependency_overrides.clear()
    app.dependency_overrides[bank_accounts.get_db]=override
    app.dependency_overrides[daily_closing.get_db]=override
    app.dependency_overrides[cash_counts.get_db]=override
    app.dependency_overrides[cash_drawer_movements.get_db]=override
    try:
        client=TestClient(app)
        url=f"/companies/{cid}/bank-accounts"
        now=datetime.now(timezone.utc).isoformat()
        first=client.post(url,json={"bank_name":"測試銀行","account_name":"營運帳戶","account_last4":"1234","opening_balance":"10000.00","opening_balance_at":now})
        second=client.post(url,json={"bank_name":"測試銀行","account_name":"備用帳戶","account_last4":"5678","opening_balance":"2000.00","opening_balance_at":now})
        assert first.status_code==201,first.text
        assert second.status_code==201,second.text
        a,b=first.json()["id"],second.json()["id"]
        deposit=client.post(f"{url}/{a}/cash-deposits",json={"site_id":str(sid),"amount":"1500.00","created_by_name":"店員甲","reference_no":"D-001"})
        assert deposit.status_code==201,deposit.text
        assert deposit.json()["transaction_type"]=="CASH_DEPOSIT"
        withdrawal=client.post(f"{url}/{a}/cash-withdrawals",json={"site_id":str(sid),"amount":"500.00","created_by_name":"店員甲","reference_no":"W-001"})
        assert withdrawal.status_code==201,withdrawal.text
        transfer=client.post(f"{url}/transfers",json={"from_account_id":a,"to_account_id":b,"amount":"1000.00","created_by_name":"店員甲","reference_no":"T-001"})
        assert transfer.status_code==201,transfer.text
        assert len(transfer.json())==2
        assert transfer.json()[0]["transfer_group_id"]==transfer.json()[1]["transfer_group_id"]
        accounts=client.get(url)
        assert accounts.status_code==200,accounts.text
        balances={x["account"]["id"]:x["current_balance"] for x in accounts.json()}
        assert balances[a]=="10000.00"
        assert balances[b]=="3000.00"
        too_much=client.post(f"{url}/{b}/cash-withdrawals",json={"site_id":str(sid),"amount":"99999.00","created_by_name":"店員甲"})
        assert too_much.status_code==422
        check=Session()
        assert check.query(BankTransaction).count()==4
        assert check.query(CashDrawerMovement).count()==2
        assert check.query(CashDrawerMovement).filter(CashDrawerMovement.bank_transaction_id.is_not(None)).count()==2
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
