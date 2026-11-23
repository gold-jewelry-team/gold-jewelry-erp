from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.cash_count import DailyCashCount
from app.models.daily_closing import DailyClosing
from app.models.site import Site
from app.routers import cash_counts, cash_drawer_movements, daily_closing


def _cash_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="CASH-TEST", name="現金盤點測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.commit()
    ids = (company.id, site.id)
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[daily_closing.get_db] = override_db
    app.dependency_overrides[cash_counts.get_db] = override_db
    app.dependency_overrides[cash_drawer_movements.get_db] = override_db
    return engine, TestSession, ids


def test_cash_count_includes_drawer_movements_and_requires_independent_review():
    engine, TestSession, (company_id, site_id) = _cash_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/sites/{site_id}"

        deposit = client.post(f"{base}/cash-drawer-movements", json={
            "movement_type": "BANK_DEPOSIT",
            "amount": "100.00",
            "description": "存入銀行",
            "created_by_name": "店員甲",
        })
        assert deposit.status_code == 201, deposit.text
        assert deposit.json()["direction"] == "OUT"

        float_increase = client.post(f"{base}/cash-drawer-movements", json={
            "movement_type": "FLOAT_INCREASE",
            "amount": "50.00",
            "description": "增加備用金",
            "created_by_name": "店員甲",
        })
        assert float_increase.status_code == 201, float_increase.text
        assert float_increase.json()["direction"] == "IN"

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        close = client.post(
            f"{base}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text
        closing_id = close.json()["id"]

        summaries = {
            item["payment_method"]: item
            for item in close.json()["payment_summaries"]
        }
        assert summaries["CASH"]["cash_drawer_in_amount"] == "50.00"
        assert summaries["CASH"]["cash_drawer_out_amount"] == "100.00"

        count_url = f"{base}/daily-closings/{closing_id}/cash-count"
        count = client.post(count_url, json={
            "opening_cash_float": "1000.00",
            "counted_cash_amount": "940.00",
            "counted_by_name": "店員甲",
            "count_note": "打烊盤點",
        })
        assert count.status_code == 201, count.text
        result = count.json()
        assert result["expected_cash_amount"] == "950.00"
        assert result["cash_variance"] == "-10.00"

        duplicate = client.post(count_url, json={
            "opening_cash_float": "1000.00",
            "counted_cash_amount": "950.00",
            "counted_by_name": "店員甲",
        })
        assert duplicate.status_code == 422

        same_person_review = client.post(
            f"{count_url}/{result['id']}/review",
            json={"reviewed_by_name": "店員甲"},
        )
        assert same_person_review.status_code == 422

        reviewed = client.post(
            f"{count_url}/{result['id']}/review",
            json={
                "reviewed_by_name": "主管乙",
                "review_note": "已確認短少 10 元",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["reviewed_by_name"] == "主管乙"

        duplicate_review = client.post(
            f"{count_url}/{result['id']}/review",
            json={"reviewed_by_name": "主管丙"},
        )
        assert duplicate_review.status_code == 422

        check = TestSession()
        assert check.query(DailyCashCount).count() == 1
        assert check.query(DailyClosing).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_cash_drawer_movement_is_rejected_after_daily_closing():
    engine, _TestSession, (company_id, site_id) = _cash_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/sites/{site_id}"
        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        close = client.post(
            f"{base}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text

        movement = client.post(f"{base}/cash-drawer-movements", json={
            "movement_type": "OTHER_IN",
            "amount": "10.00",
            "description": "結帳後不應新增",
            "created_by_name": "店員甲",
        })
        assert movement.status_code == 422
        assert "已結帳" in movement.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_cash_count_and_review_are_scoped_to_the_exact_site_and_closing():
    engine, TestSession, (company_id, site_id) = _cash_context()
    try:
        db = TestSession()
        company = db.get(Company, company_id)
        other_site = Site(company_id=company_id, code="BRANCH", name="分店")
        other_company = Company(code="CASH-OTHER", name="其他公司")
        db.add_all([other_site, other_company])
        db.flush()
        foreign_site_id = other_site.id
        foreign_company_site = Site(
            company_id=other_company.id, code="MAIN", name="其他公司總店"
        )
        db.add(foreign_company_site)
        db.commit()
        foreign_company_id = other_company.id
        foreign_company_site_id = foreign_company_site.id
        db.close()

        client = TestClient(app)
        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        primary_close = client.post(
            f"/companies/{company_id}/sites/{site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert primary_close.status_code == 201, primary_close.text
        primary_closing_id = primary_close.json()["id"]

        other_site_close = client.post(
            f"/companies/{company_id}/sites/{foreign_site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert other_site_close.status_code == 201, other_site_close.text
        other_closing_id = other_site_close.json()["id"]

        foreign_company_close = client.post(
            f"/companies/{foreign_company_id}/sites/{foreign_company_site_id}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert foreign_company_close.status_code == 201, foreign_company_close.text

        primary_url = (
            f"/companies/{company_id}/sites/{site_id}/daily-closings/"
            f"{primary_closing_id}/cash-count"
        )
        count = client.post(primary_url, json={
            "opening_cash_float": "500.00",
            "counted_cash_amount": "500.00",
            "counted_by_name": "店員甲",
        })
        assert count.status_code == 201, count.text
        count_id = count.json()["id"]

        wrong_closing_review = client.post(
            f"{primary_url.replace(str(primary_closing_id), str(other_closing_id))}/"
            f"{count_id}/review",
            json={"reviewed_by_name": "主管乙"},
        )
        assert wrong_closing_review.status_code == 422

        wrong_site_count = client.post(
            f"/companies/{company_id}/sites/{foreign_site_id}/daily-closings/"
            f"{primary_closing_id}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "500.00",
                "counted_by_name": "店員甲",
            },
        )
        assert wrong_site_count.status_code == 422

        wrong_company_count = client.post(
            f"/companies/{foreign_company_id}/sites/{foreign_company_site_id}/"
            f"daily-closings/{primary_closing_id}/cash-count",
            json={
                "opening_cash_float": "500.00",
                "counted_cash_amount": "500.00",
                "counted_by_name": "店員甲",
            },
        )
        assert wrong_company_count.status_code == 422

        check = TestSession()
        from uuid import UUID
        saved = check.get(DailyCashCount, UUID(count_id))
        assert saved is not None
        assert saved.reviewed_at is None
        assert check.query(DailyCashCount).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_cash_count_rejects_negative_expected_drawer_balance_without_database_error():
    engine, TestSession, (company_id, site_id) = _cash_context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}/sites/{site_id}"
        deposit = client.post(f"{base}/cash-drawer-movements", json={
            "movement_type": "BANK_DEPOSIT",
            "amount": "100.00",
            "description": "測試超出可用現金的存款",
            "created_by_name": "店員甲",
        })
        assert deposit.status_code == 201, deposit.text

        business_date = datetime.now(timezone.utc).astimezone(
            ZoneInfo("Asia/Taipei")
        ).date()
        close = client.post(
            f"{base}/daily-closings",
            json={"business_date": business_date.isoformat()},
        )
        assert close.status_code == 201, close.text

        count = client.post(
            f"{base}/daily-closings/{close.json()['id']}/cash-count",
            json={
                "opening_cash_float": "0.00",
                "counted_cash_amount": "0.00",
                "counted_by_name": "店員甲",
            },
        )
        assert count.status_code == 422, count.text
        assert "預期現金為負數" in count.json()["detail"]

        verify = TestSession()
        assert verify.query(DailyCashCount).count() == 0
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
