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
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.routers import sales
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_mixed_catalog_and_estimate_completion_rolls_back_all_stock_on_shortage():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()

    company = Company(code="SALE-ATOMIC", name="銷售原子性測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    location = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    first = Product(
        company_id=company.id,
        product_code="ATOMIC-G-001",
        barcode="ATOMIC-BAR-001",
        name="有庫存黃金戒指",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    second = Product(
        company_id=company.id,
        product_code="ATOMIC-G-002",
        barcode="ATOMIC-BAR-002",
        name="缺貨黃金項鍊",
        gross_weight=Decimal("1.2000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        labor_fee=Decimal("300"),
    )
    session.add_all([location, first, second])
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
    create_inventory_movement(
        session,
        company_id=company.id,
        site_id=site.id,
        product_id=first.id,
        movement_type="RECEIPT",
        quantity=Decimal("1"),
        to_location_id=location.id,
        weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        reference_type="TEST",
    )
    session.commit()
    company_id, site_id = company.id, site.id
    first_id, second_id, location_id = first.id, second.id, location.id
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(f"/companies/{company_id}/sales", json={
            "site_id": str(site_id),
            "sale_no": "SO-ATOMIC-001",
            "payment_method": "CASH",
            "lines": [
                {
                    "product_id": str(first_id),
                    "source_location_id": str(location_id),
                },
                {
                    "product_id": str(second_id),
                    "source_location_id": str(location_id),
                },
                {
                    "product_name": "臨時估價手環",
                    "product_code": "臨時估價",
                    "net_weight": "0.5000",
                    "weight_unit_code": "QIAN",
                    "labor_fee": "200",
                },
            ],
        })
        assert created.status_code == 201, created.text
        sale = created.json()
        assert sale["status"] == "DRAFT"
        assert [line["product_id"] for line in sale["lines"]] == [
            str(first_id), str(second_id), None
        ]

        # The first catalog item can be moved in the transaction, but the
        # second item is out of stock. The API must roll back the first move
        # and leave the draft retryable; the estimate must never affect stock.
        failed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert failed.status_code == 422
        assert "庫存不足" in failed.json()["detail"]

        check = TestSession()
        persisted_sale = check.get(models.Sale, UUID(sale["id"]))
        assert persisted_sale.status == "DRAFT"
        assert get_stock_balance(
            check, product_id=first_id, location_id=location_id
        ) == Decimal("1")
        assert get_stock_balance(
            check, product_id=second_id, location_id=location_id
        ) == Decimal("0")
        assert check.query(InventoryMovement).filter_by(
            reference_type="SALE_LINE"
        ).count() == 0
        check.close()

        # Receive the missing item and retry the same draft.
        receipt_session = TestSession()
        create_inventory_movement(
            receipt_session,
            company_id=company_id,
            site_id=site_id,
            product_id=second_id,
            movement_type="RECEIPT",
            quantity=Decimal("1"),
            to_location_id=location_id,
            weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
            reference_type="TEST-RECEIPT",
        )
        receipt_session.commit()
        receipt_session.close()

        completed = client.post(
            f"/companies/{company_id}/sales/{sale['id']}/complete"
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"

        final_check = TestSession()
        assert get_stock_balance(
            final_check, product_id=first_id, location_id=location_id
        ) == Decimal("0")
        assert get_stock_balance(
            final_check, product_id=second_id, location_id=location_id
        ) == Decimal("0")
        sale_movements = list(final_check.query(InventoryMovement).filter_by(
            reference_type="SALE_LINE"
        ).all())
        assert len(sale_movements) == 2
        assert {movement.product_id for movement in sale_movements} == {
            first_id, second_id
        }
        final_check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
