from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.sale import Sale
from app.models.site import Site
from app.routers import sales
from app.services.daily_closing import create_daily_closing


def test_sale_draft_api_rejects_new_sale_after_business_day_is_closed():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="SALE-CLOSED-DAY", name="結帳後禁止新增銷售測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    business_date = datetime.now(ZoneInfo("Asia/Taipei")).date()
    closing = create_daily_closing(
        db,
        company_id=company.id,
        site_id=site.id,
        business_date=business_date,
    )
    db.commit()
    company_id, site_id = company.id, site.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/sales",
            json={
                "site_id": str(site_id),
                "sale_no": "SO-CLOSED-DAY-001",
                "payment_method": "CASH",
                "lines": [{
                    "product_name": "臨時估價黃金戒指",
                    "net_weight": "1.0000",
                    "weight_unit_code": "QIAN",
                    "labor_fee": "200.00",
                }],
            },
        )
        assert response.status_code == 422
        assert "已結帳" in response.json()["detail"]

        verify = TestSession()
        sale_count = verify.scalar(
            select(func.count()).select_from(Sale).where(
                Sale.company_id == company_id
            )
        )
        assert sale_count == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
