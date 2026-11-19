from datetime import date, datetime, timezone
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
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.daily_closing import DailyClosing
from app.routers import daily_closing, cash_counts, cash_drawer_movements

def test_bank_deposit_updates_cash_drawer_expected_balance_and_closing_snapshot():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="DRAWER",name="現金櫃異動測試銀樓"); db.add(company); db.flush()
    site=Site(company_id=company.id,code="MAIN",name="總店"); db.add(site); db.commit()
    cid,sid=company.id,site.id; db.close()
    def override():
        s=Session()
        try: yield s
        finally: s.close()
    app.dependency_overrides.clear()
    app.dependency_overrides[daily_closing.get_db]=override
    app.dependency_overrides[cash_counts.get_db]=override
    app.dependency_overrides[cash_drawer_movements.get_db]=override
    try:
        client=TestClient(app)
        movement_url=f"/companies/{cid}/sites/{sid}/cash-drawer-movements"
        movement=client.post(movement_url,json={
            "movement_type":"BANK_DEPOSIT","amount":"400.00",
            "description":"存入銀行","created_by_name":"店員甲","reference_no":"DEP-001"
        })
        assert movement.status_code==201,movement.text
        assert movement.json()["direction"]=="OUT"
        business_date=datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
        close=client.post(f"/companies/{cid}/sites/{sid}/daily-closings",json={"business_date":business_date.isoformat()})
        assert close.status_code==201,close.text
        body=close.json()
        assert body["cash_drawer_out_amount"]=="400.00"
        cash_summary=next(x for x in body["payment_summaries"] if x["payment_method"]=="CASH")
        assert cash_summary["cash_drawer_out_amount"]=="400.00"
        assert cash_summary["net_cash_flow"]=="-400.00"
        cash_url=f"/companies/{cid}/sites/{sid}/daily-closings/{body['id']}/cash-count"
        counted=client.post(cash_url,json={"opening_cash_float":"1000.00","counted_cash_amount":"600.00","counted_by_name":"店員甲"})
        assert counted.status_code==201,counted.text
        assert counted.json()["expected_cash_amount"]=="600.00"
        assert counted.json()["cash_variance"]=="0.00"
        blocked=client.post(movement_url,json={
            "movement_type":"BANK_WITHDRAWAL","amount":"100.00",
            "description":"結帳後不得新增","created_by_name":"店員甲"
        })
        assert blocked.status_code==422
        check=Session()
        assert check.query(CashDrawerMovement).count()==1
        assert check.query(DailyClosing).count()==1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
