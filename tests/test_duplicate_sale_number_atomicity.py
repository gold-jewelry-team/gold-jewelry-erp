from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.sale import Sale, SaleLine
from app.models.site import Site
from app.routers import sales


def test_duplicate_sale_number_returns_conflict_without_partial_sale_records():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="SALE-DUPLICATE-NO", name="重複銷售單號測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_all([
        GoldPrice(
            company_id=company.id, site_id=None, price_type="SELL",
            price_value=Decimal("12000"), currency_code="TWD",
            unit_code="QIAN", effective_at=effective_at, source="MANUAL",
        ),
        GoldPrice(
            company_id=company.id, site_id=None, price_type="BUY",
            price_value=Decimal("11000"), currency_code="TWD",
            unit_code="QIAN", effective_at=effective_at, source="MANUAL",
        ),
    ])
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
        payload = {
            "site_id": str(site_id),
            "sale_no": "SO-DUPLICATE-001",
            "payment_method": "CASH",
            "lines": [{
                "product_name": "臨時估價黃金戒指",
                "net_weight": "1.0000",
                "weight_unit_code": "QIAN",
                "labor_fee": "300.00",
            }],
        }
        first = client.post(f"/companies/{company_id}/sales", json=payload)
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]
        assert len(first.json()["lines"]) == 1

        duplicate = client.post(f"/companies/{company_id}/sales", json=payload)
        assert duplicate.status_code == 409, duplicate.text
        assert "銷售單號重複" in duplicate.json()["detail"]

        verify = TestSession()
        persisted_sales = list(verify.scalars(
            select(Sale).where(Sale.company_id == company_id)
        ).all())
        persisted_lines = list(verify.scalars(
            select(SaleLine).join(SaleLine.sale).where(Sale.company_id == company_id)
        ).all())
        assert len(persisted_sales) == 1
        assert str(persisted_sales[0].id) == first_id
        assert persisted_sales[0].sale_no == "SO-DUPLICATE-001"
        assert persisted_sales[0].status == "DRAFT"
        assert len(persisted_lines) == 1
        assert persisted_lines[0].sale_id == persisted_sales[0].id
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
