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
from app.models.sale import Sale
from app.models.payment_transaction import PaymentTransaction
from app.models.daily_closing import DailyClosing
from app.models.cash_count import DailyCashCount
from app.routers import daily_closing, cash_counts

def test_cash_count_variance_and_independent_review():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    db=Session()
    company=Company(code="CASH-COUNT",name="現金盤點測試銀樓"); db.add(company); db.flush()
    site=Site(company_id=company.id,code="MAIN",name="總店"); db.add(site); db.flush()
    sale=Sale(company_id=company.id,site_id=site.id,sale_no="CASH-001",status="COMPLETED",payment_method="CASH",currency_code="TWD",subtotal=Decimal("500"),card_fee=Decimal("0"),final_amount=Decimal("500"),completed_at=datetime(2026,11,19,2,0,tzinfo=timezone.utc))
    db.add(sale); db.flush()
    db.add(PaymentTransaction(company_id=company.id,site_id=site.id,sale_id=sale.id,direction="IN",payment_method="CASH",amount=Decimal("500"),currency_code="TWD",paid_at=datetime(2026,11,19,3,0,tzinfo=timezone.utc)))
    db.commit(); cid,sid=company.id,site.id; db.close()
    def override_closing():
        s=Session()
        try: yield s
        finally: s.close()
    def override_count():
        s=Session()
        try: yield s
        finally: s.close()
    app.dependency_overrides.clear()
    app.dependency_overrides[daily_closing.get_db]=override_closing
    app.dependency_overrides[cash_counts.get_db]=override_count
    try:
        client=TestClient(app)
        close=client.post(f"/companies/{cid}/sites/{sid}/daily-closings",json={"business_date":"2026-11-19"})
        assert close.status_code==201,close.text
        closing_id=close.json()["id"]
        url=f"/companies/{cid}/sites/{sid}/daily-closings/{closing_id}/cash-count"
        counted=client.post(url,json={"opening_cash_float":"1000.00","counted_cash_amount":"1480.00","counted_by_name":"店員甲"})
        assert counted.status_code==201,counted.text
        body=counted.json()
        assert body["expected_cash_amount"]=="1500.00"
        assert body["cash_variance"]=="-20.00"
        assert body["reviewed_at"] is None
        duplicate=client.post(url,json={"opening_cash_float":"1000.00","counted_cash_amount":"1500.00","counted_by_name":"店員甲"})
        assert duplicate.status_code==422
        same=client.post(f"{url}/{body['id']}/review",json={"reviewed_by_name":"店員甲"})
        assert same.status_code==422
        reviewed=client.post(f"{url}/{body['id']}/review",json={"reviewed_by_name":"店長乙","review_note":"已核對現金"})
        assert reviewed.status_code==200,reviewed.text
        assert reviewed.json()["reviewed_by_name"]=="店長乙"
        again=client.post(f"{url}/{body['id']}/review",json={"reviewed_by_name":"店長丙"})
        assert again.status_code==422
        check=Session(); assert check.query(DailyCashCount).count()==1; assert check.query(DailyClosing).count()==1; check.close()
    finally:
        app.dependency_overrides.clear(); engine.dispose()
