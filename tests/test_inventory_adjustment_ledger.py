from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.services.inventory import create_inventory_movement, get_stock_balance


def test_positive_and_negative_adjustments_reconcile_location_stock():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="ADJUST", name="盤點調整測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        product = Product(company_id=company.id, product_code="ADJ-001", name="盤點商品")
        session.add_all([location, product])
        session.flush()

        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("5"), to_location_id=location.id,
        )
        plus = create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="ADJUSTMENT", quantity=Decimal("2"), to_location_id=location.id,
            reference_type="STOCKTAKE", reference_id=None, note="盤點溢餘",
        )
        minus = create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="ADJUSTMENT", quantity=Decimal("3"), from_location_id=location.id,
            reference_type="STOCKTAKE", reference_id=None, note="盤點短少",
        )
        session.commit()

        assert plus.to_location_id == location.id and plus.from_location_id is None
        assert minus.from_location_id == location.id and minus.to_location_id is None
        assert get_stock_balance(session, product_id=product.id, location_id=location.id) == Decimal("4")
        assert session.query(InventoryMovement).count() == 3

        with pytest.raises(ValueError, match="庫存不足"):
            create_inventory_movement(
                session, company_id=company.id, site_id=site.id, product_id=product.id,
                movement_type="ADJUSTMENT", quantity=Decimal("5"), from_location_id=location.id,
            )
        session.rollback()
        assert session.query(InventoryMovement).count() == 3
        assert get_stock_balance(session, product_id=product.id, location_id=location.id) == Decimal("4")
    finally:
        session.close()
        engine.dispose()
