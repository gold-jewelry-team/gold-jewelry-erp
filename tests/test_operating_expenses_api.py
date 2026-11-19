from datetime import datetime, timezone
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
from app.models.operating_expense import OperatingExpense
from app.routers import expenses, daily_closing

def test_operating_expense_create_pay_and_daily_closing():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session(); company=Company(code="EXP",name="費用測試銀樓"); db.add(company); db.flush()
    site=Site(company_id=company.id,code="MAIN",name="總店"); db.add(site); db.commit()
    cid,sid=company.id,site.id; db.close()
    def override():
        s=Session()
        try: yield s
        finally: s.close()
    app.dependency_overrides.clear(); app.dependency_overrides[expenses.get_db]=override; app.dependency_overrides[daily_closing.get_db]=override
    try:
        client=TestClient(app); base=f"/companies/{cid}/operating-expenses"
        created=client.post(base,json={"site_id":str(sid),"expense_no":"EXP-001","expense_date":"2026-11-19","category_code":"UTILITIES","description":"電費","amount":"1200.00"})
        assert created.status_code==201,created.text
        assert created.json()["status"]=="UNPAID"
        paid=client.post(f"{base}/{created.json()['id']}/pay",json={"payment_method":"TRANSFER"})
        assert paid.status_code==200,paid.text
        assert paid.json()["status"]=="PAID"
        today=datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
        close=client.post(f"/companies/{cid}/sites/{sid}/daily-closings",json={"business_date":today.isoformat()})
        assert close.status_code==201,close.text
        assert close.json()["expenses_paid_amount"]=="1200.00"
        assert close.json()["net_cash_flow"]=="-1200.00"
        check=Session(); assert check.query(OperatingExpense).count()==1; check.close()
    finally:
        app.dependency_overrides.clear(); engine.dispose()
