from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

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
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales, sales_returns
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_multi_item_return_rolls_back_all_restocking_when_later_item_fails():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()

    company = Company(code="RETURN-ATOMIC", name="退貨原子性測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    first_location = StorageLocation(
        site_id=site.id, code="SAFE-A", name="保險櫃 A", location_type="SAFE"
    )
    second_location = StorageLocation(
        site_id=site.id, code="SAFE-B", name="保險櫃 B", location_type="SAFE"
    )
    first_product = Product(
        company_id=company.id,
        product_code="RETURN-ATOMIC-001",
        barcode="RETURN-ATOMIC-BAR-001",
        name="退貨原子性測試戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    second_product = Product(
        company_id=company.id,
        product_code="RETURN-ATOMIC-002",
        barcode="RETURN-ATOMIC-BAR-002",
        name="退貨原子性測試項鍊",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    session.add_all([first_location, second_location, first_product, second_product])
    session.flush()

    effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.add_all([
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
    for product, location in (
        (first_product, first_location),
        (second_product, second_location),
    ):
        create_inventory_movement(
            session,
            company_id=company.id,
            site_id=site.id,
            product_id=product.id,
            movement_type="RECEIPT",
            quantity=Decimal("1"),
            to_location_id=location.id,
            weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
            reference_type="TEST-RECEIPT",
        )
    session.commit()

    company_id, site_id = company.id, site.id
    first_product_id, second_product_id = first_product.id, second_product.id
    first_location_id, second_location_id = first_location.id, second_location.id
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
            "sale_no": "SO-RETURN-ATOMIC-001",
            "payment_method": "CASH",
            "lines": [
                {
                    "product_id": str(first_product_id),
                    "source_location_id": str(first_location_id),
                },
                {
                    "product_id": str(second_product_id),
                    "source_location_id": str(second_location_id),
                },
            ],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        completed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        # The first return line can be restocked, but the second destination
        # becomes inactive. The failed request must roll back the first line,
        # the return header, and every return-line record as one transaction.
        deactivate = TestSession()
        second_location = deactivate.get(StorageLocation, second_location_id)
        second_location.is_active = False
        deactivate.commit()
        deactivate.close()

        failed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-ATOMIC-001",
                "sale_line_ids": [line["id"] for line in sale["lines"]],
                "reason": "驗證多件退貨的交易原子性",
            },
        )
        assert failed.status_code == 422
        assert "儲存位置" in failed.json()["detail"]

        check = TestSession()
        assert check.query(SaleReturn).count() == 0
        assert check.query(models.SaleReturnLine).count() == 0
        assert check.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).count() == 0
        assert get_stock_balance(
            check, product_id=first_product_id, location_id=first_location_id
        ) == Decimal("0")
        assert get_stock_balance(
            check, product_id=second_product_id, location_id=second_location_id
        ) == Decimal("0")
        check.close()

        # Restore the location and retry the same return number. Both items
        # must be restocked exactly once, with no remnants from the failed try.
        reactivate = TestSession()
        reactivate.get(StorageLocation, second_location_id).is_active = True
        reactivate.commit()
        reactivate.close()

        returned = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/returns",
            json={
                "return_no": "RT-RETURN-ATOMIC-001",
                "sale_line_ids": [line["id"] for line in sale["lines"]],
                "reason": "重新完成多件退貨",
            },
        )
        assert returned.status_code == 201, returned.text
        assert len(returned.json()["lines"]) == 2

        final_check = TestSession()
        assert final_check.query(SaleReturn).count() == 1
        assert final_check.query(models.SaleReturnLine).count() == 2
        assert final_check.query(InventoryMovement).filter_by(
            reference_type="SALE_RETURN_LINE"
        ).count() == 2
        assert get_stock_balance(
            final_check, product_id=first_product_id, location_id=first_location_id
        ) == Decimal("1")
        assert get_stock_balance(
            final_check, product_id=second_product_id, location_id=second_location_id
        ) == Decimal("1")
        final_check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
