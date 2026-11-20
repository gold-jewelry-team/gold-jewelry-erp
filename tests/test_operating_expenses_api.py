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

        listed = client.get(base, params={"site_id": str(sid), "status": "PAID"})
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == created.json()["id"]
        today=datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
        close=client.post(f"/companies/{cid}/sites/{sid}/daily-closings",json={"business_date":today.isoformat()})
        assert close.status_code==201,close.text
        assert close.json()["expenses_paid_amount"]=="1200.00"
        assert close.json()["net_cash_flow"]=="-1200.00"
        check=Session(); assert check.query(OperatingExpense).count()==1; check.close()
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_unpaid_expense_cannot_be_paid_after_daily_closing():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from app.models.daily_closing import DailyClosing

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    company = Company(code="EXP-CLOSED", name="結帳後費用付款測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[expenses.get_db] = override
    app.dependency_overrides[daily_closing.get_db] = override
    try:
        client = TestClient(app)
        base_url = f"/companies/{company_id}/operating-expenses"
        created = client.post(base_url, json={
            "site_id": str(site_id),
            "expense_no": "EXP-CLOSED-001",
            "expense_date": "2026-11-20",
            "category_code": "UTILITIES",
            "description": "尚未付款的水電費",
            "amount": "850.00",
        })
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "UNPAID"

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        closing = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert closing.status_code == 201, closing.text

        paid = client.post(
            f"{base_url}/{created.json()['id']}/pay",
            json={"payment_method": "CASH"},
        )
        assert paid.status_code == 422
        assert "已結帳" in paid.json()["detail"]

        refreshed = client.get(
            base_url, params={"site_id": str(site_id), "status": "UNPAID"}
        )
        assert refreshed.status_code == 200, refreshed.text
        assert len(refreshed.json()) == 1
        assert refreshed.json()[0]["status"] == "UNPAID"
        assert refreshed.json()[0]["paid_at"] is None

        check = Session()
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
