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
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.daily_closing import DailyClosing
from app.routers import daily_closing, cash_counts, cash_drawer_movements


def test_bank_transfers_update_drawer_balance_but_not_operating_cash_flow():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    company = Company(code="DRAWER", name="現金櫃異動測試銀樓")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    cid, sid = company.id, site.id
    db.close()

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[daily_closing.get_db] = override
    app.dependency_overrides[cash_counts.get_db] = override
    app.dependency_overrides[cash_drawer_movements.get_db] = override
    try:
        client = TestClient(app)
        movement_url = f"/companies/{cid}/sites/{sid}/cash-drawer-movements"
        deposit = client.post(movement_url, json={
            "movement_type": "BANK_DEPOSIT",
            "amount": "400.00",
            "description": "存入銀行",
            "created_by_name": "店員甲",
            "reference_no": "DEP-001",
        })
        assert deposit.status_code == 201, deposit.text
        assert deposit.json()["direction"] == "OUT"

        withdrawal = client.post(movement_url, json={
            "movement_type": "BANK_WITHDRAWAL",
            "amount": "100.00",
            "description": "銀行提款",
            "created_by_name": "店員甲",
            "reference_no": "WDR-001",
        })
        assert withdrawal.status_code == 201, withdrawal.text
        assert withdrawal.json()["direction"] == "IN"

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        close = client.post(
            f"/companies/{cid}/sites/{sid}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text
        body = close.json()
        assert body["cash_drawer_out_amount"] == "400.00"
        assert body["cash_drawer_in_amount"] == "100.00"
        # Bank transfers affect physical drawer cash, not operating cash flow.
        assert body["net_cash_flow"] == "0.00"
        cash_summary = next(
            row for row in body["payment_summaries"] if row["payment_method"] == "CASH"
        )
        assert cash_summary["cash_drawer_out_amount"] == "400.00"
        assert cash_summary["cash_drawer_in_amount"] == "100.00"
        assert cash_summary["net_cash_flow"] == "0.00"

        cash_url = f"/companies/{cid}/sites/{sid}/daily-closings/{body['id']}/cash-count"
        counted = client.post(cash_url, json={
            "opening_cash_float": "1000.00",
            "counted_cash_amount": "700.00",
            "counted_by_name": "店員甲",
        })
        assert counted.status_code == 201, counted.text
        assert counted.json()["expected_cash_amount"] == "700.00"
        assert counted.json()["cash_variance"] == "0.00"

        blocked = client.post(movement_url, json={
            "movement_type": "BANK_WITHDRAWAL",
            "amount": "100.00",
            "description": "結帳後不得新增",
            "created_by_name": "店員甲",
        })
        assert blocked.status_code == 422

        check = Session()
        assert check.query(CashDrawerMovement).count() == 2
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
