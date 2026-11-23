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
from app.models.sale import Sale
from app.models.site import Site
from app.routers import sales


def test_sales_history_date_range_uses_inclusive_taipei_calendar_day():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="SALE-DATE-BOUNDARY", name="銷售日期邊界測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()

    taipei = ZoneInfo("Asia/Taipei")
    local_midnight = datetime(2026, 11, 23, 0, 0, tzinfo=taipei)
    local_last_second = datetime(2026, 11, 23, 23, 59, 59, tzinfo=taipei)
    next_day_midnight = datetime(2026, 11, 24, 0, 0, tzinfo=taipei)
    moments = (
        ("SO-DATE-START", local_midnight),
        ("SO-DATE-END", local_last_second),
        ("SO-DATE-NEXT", next_day_midnight),
    )
    for sale_no, local_time in moments:
        db.add(Sale(
            company_id=company.id,
            site_id=site.id,
            sale_no=sale_no,
            status="DRAFT",
            payment_method="CASH",
            currency_code="TWD",
            subtotal=Decimal("0.00"),
            card_amount=Decimal("0.00"),
            card_fee=Decimal("0.00"),
            final_amount=Decimal("0.00"),
            created_at=local_time.astimezone(timezone.utc),
            updated_at=local_time.astimezone(timezone.utc),
        ))
    db.commit()
    company_id = company.id
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
        response = client.get(
            f"/companies/{company_id}/sales",
            params={"from_date": "2026-11-23", "to_date": "2026-11-23"},
        )
        assert response.status_code == 200, response.text
        sale_numbers = {item["sale_no"] for item in response.json()}
        assert sale_numbers == {"SO-DATE-START", "SO-DATE-END"}
        assert "SO-DATE-NEXT" not in sale_numbers
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
