from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.inventory import InventoryMovement
from app.models.site import Site
from app.routers import sales, sales_returns


def test_temporary_estimate_sale_is_snapshotted_without_inventory_movement():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()

    company = Company(code="ESTIMATE-SALE", name="臨時估價成交測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.add_all([
        GoldPrice(company_id=company.id, site_id=None, price_type="SELL",
                  price_value=Decimal("12000"), currency_code="TWD",
                  unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
        GoldPrice(company_id=company.id, site_id=None, price_type="BUY",
                  price_value=Decimal("11000"), currency_code="TWD",
                  unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
    ])
    session.commit()
    company_id, site_id = company.id, site.id
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    app.dependency_overrides[sales_returns.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-ESTIMATE-001",
            "payment_method": "CASH",
            "lines": [{
                "product_name": "臨時估價女戒",
                "product_code": "臨時估價",
                "net_weight": "1.0000",
                "weight_unit_code": "QIAN",
                "labor_fee": "500",
            }],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        assert sale["status"] == "DRAFT"
        assert sale["subtotal"] == "12500.00"
        line = sale["lines"][0]
        assert line["product_id"] is None
        assert line["source_location_id"] is None
        assert line["product_name_snapshot"] == "臨時估價女戒"
        assert line["net_weight"] == "1.0000"
        assert line["sell_gold_price_value"] == "12000.0000"

        completed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        returned = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-ESTIMATE-001",
                "sale_line_ids": [line["id"]],
                "reason": "臨時估價商品取消",
            },
        )
        assert returned.status_code == 201, returned.text
        return_line = returned.json()["lines"][0]
        assert return_line["product_id"] is None
        assert return_line["source_location_id"] is None
        assert return_line["settlement_reversal_amount"] == "-12500.00"

        refund_sale_response = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-ESTIMATE-REFUND-001",
            "payment_method": "CASH",
            "lines": [{
                "product_name": "臨時估價手環",
                "net_weight": "1.0000",
                "weight_unit_code": "QIAN",
                "labor_fee": "500",
                "old_gold_weight": "1.5000",
                "trade_in_source": "EXTERNAL",
                "trade_in_ratio": "0.95",
            }],
        })
        assert refund_sale_response.status_code == 201, refund_sale_response.text
        refund_sale = refund_sale_response.json()
        assert refund_sale["subtotal"] == "-4120.00"
        assert refund_sale["final_amount"] == "-4120.00"
        refund_completed = client.post(
            f"/companies/{company_id}/sales/{refund_sale['id']}/complete"
        )
        assert refund_completed.status_code == 200, refund_completed.text
        assert refund_completed.json()["status"] == "COMPLETED"

        refund_return = client.post(
            f"/companies/{company_id}/sales/{refund_sale['id']}/returns",
            json={
                "return_no": "RT-ESTIMATE-REFUND-001",
                "sale_line_ids": [refund_sale["lines"][0]["id"]],
                "reason": "舊金超額退款測試",
            },
        )
        assert refund_return.status_code == 201, refund_return.text
        assert refund_return.json()["settlement_reversal_amount"] == "4120.00"

        check_session = TestSession()
        assert check_session.query(InventoryMovement).count() == 0
        check_session.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
