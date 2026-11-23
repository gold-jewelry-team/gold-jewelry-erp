from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_historical_balances_reflect_transfer_only_after_transfer_timestamp():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="HISTORY", name="庫存歷史測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        product = Product(company_id=company.id, product_code="G-HISTORY-001", name="歷史庫存測試商品")
        session.add_all([safe, show, product])
        session.flush()
        received_at = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
        transferred_at = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("5"), to_location_id=safe.id,
            occurred_at=received_at,
        )
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="TRANSFER", quantity=Decimal("2"),
            from_location_id=safe.id, to_location_id=show.id,
            occurred_at=transferred_at,
        )
        session.commit()

        before_transfer = datetime(2026, 11, 21, 9, 59, tzinfo=timezone.utc)
        after_transfer = datetime(2026, 11, 21, 10, 1, tzinfo=timezone.utc)
        assert get_stock_balance(
            session, product_id=product.id, location_id=safe.id, as_of=before_transfer
        ) == Decimal("5")
        assert get_stock_balance(
            session, product_id=product.id, location_id=show.id, as_of=before_transfer
        ) == Decimal("0")
        assert get_stock_balance(
            session, product_id=product.id, location_id=safe.id, as_of=after_transfer
        ) == Decimal("3")
        assert get_stock_balance(
            session, product_id=product.id, location_id=show.id, as_of=after_transfer
        ) == Decimal("2")
        assert (
            get_stock_balance(session, product_id=product.id, location_id=safe.id, as_of=after_transfer)
            + get_stock_balance(session, product_id=product.id, location_id=show.id, as_of=after_transfer)
        ) == Decimal("5")
    finally:
        session.close()
        engine.dispose()
