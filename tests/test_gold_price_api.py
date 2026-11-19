from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.site import Site
from app.routers.gold_prices import get_db


def test_gold_price_api_create_history_and_effective_lookup():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as session:
            company = Company(code="API1", name="API 測試公司")
            session.add(company)
            session.flush()
            site = Site(company_id=company.id, code="MAIN", name="總店")
            session.add(site)
            session.commit()
            company_id, site_id = company.id, site.id

        client = TestClient(app)
        response = client.post(
            f"/companies/{company_id}/gold-prices",
            json={
                "price_type": "SELL",
                "price_value": "12500.0000",
                "currency_code": "TWD",
                "unit_code": "TWD_PER_QIAN",
                "effective_at": "2026-11-19T00:00:00Z",
                "source": "MANUAL",
            },
        )
        assert response.status_code == 201
        assert response.json()["price_value"] == "12500.0000"

        history = client.get(
            f"/companies/{company_id}/gold-prices",
            params={"price_type": "SELL"},
        )
        assert history.status_code == 200
        assert len(history.json()) == 1

        site_history = client.get(
            f"/companies/{company_id}/gold-prices",
            params={"price_type": "SELL", "site_id": str(site_id)},
        )
        assert site_history.status_code == 200
        assert len(site_history.json()) == 1
        assert site_history.json()[0]["site_id"] is None

        site_price = client.post(
            f"/companies/{company_id}/gold-prices",
            json={
                "site_id": str(site_id),
                "price_type": "SELL",
                "price_value": "13000.0000",
                "currency_code": "TWD",
                "unit_code": "QIAN",
                "effective_at": "2026-11-19T12:00:00Z",
                "source": "MANUAL",
            },
        )
        assert site_price.status_code == 201

        combined_history = client.get(
            f"/companies/{company_id}/gold-prices",
            params={"price_type": "SELL", "site_id": str(site_id)},
        )
        assert combined_history.status_code == 200
        assert len(combined_history.json()) == 2

        effective = client.get(
            f"/companies/{company_id}/gold-prices/effective",
            params={
                "price_type": "SELL",
                "site_id": str(site_id),
                "at": "2026-11-20T00:00:00Z",
            },
        )
        assert effective.status_code == 200
        assert effective.json()["price_value"] == "13000.0000"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_gold_price_api_rejects_unknown_company():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            f"/companies/{uuid4()}/gold-prices",
            json={
                "price_type": "BUY",
                "price_value": "11000",
                "unit_code": "TWD_PER_QIAN",
                "effective_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
