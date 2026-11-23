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


def test_transfer_cannot_overdraw_source_location_or_append_partial_ledger_row():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="NO-NEG", name="禁止負庫存測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        product = Product(company_id=company.id, product_code="G-NONEG-001", name="庫存測試商品")
        session.add_all([safe, show, product])
        session.flush()
        receipt = create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("3"), to_location_id=safe.id,
        )
        session.commit()

        with pytest.raises(ValueError, match="庫存不足"):
            create_inventory_movement(
                session, company_id=company.id, site_id=site.id, product_id=product.id,
                movement_type="TRANSFER", quantity=Decimal("4"),
                from_location_id=safe.id, to_location_id=show.id,
            )
        session.rollback()

        rows = session.query(InventoryMovement).all()
        assert [row.id for row in rows] == [receipt.id]
        assert get_stock_balance(session, product_id=product.id, location_id=safe.id) == Decimal("3")
        assert get_stock_balance(session, product_id=product.id, location_id=show.id) == Decimal("0")
    finally:
        session.close()
        engine.dispose()
