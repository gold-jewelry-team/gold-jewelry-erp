from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.product import Product, ProductCategory
from app.models.inventory import InventoryMovement


def setup_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_product_is_individually_barcoded_and_category_scoped():
    engine, session = setup_session()
    try:
        company = Company(code="JEWEL", name="測試銀樓")
        session.add(company)
        session.flush()
        category = ProductCategory(company_id=company.id, code="RING", name="戒指")
        session.add(category)
        session.flush()
        product = Product(
            company_id=company.id, category_id=category.id,
            product_code="G00R-00001", barcode="471000000001",
            name="黃金戒指", gross_weight=Decimal("1.2500"),
            net_weight=Decimal("1.2000"), weight_unit_code="QIAN",
            labor_fee=Decimal("800"),
        )
        session.add(product)
        session.commit()
        loaded = session.query(Product).one()
        assert loaded.barcode == "471000000001"
        assert loaded.net_weight == Decimal("1.2000")
        assert loaded.category_id == category.id
    finally:
        session.close()
        engine.dispose()


def test_inventory_transfer_records_both_locations_without_mutating_product():
    engine, session = setup_session()
    try:
        company = Company(code="JEWEL", name="測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        source = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        target = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        session.add_all([source, target])
        session.flush()
        product = Product(company_id=company.id, product_code="G00R-00002", name="戒指",
                          gross_weight=Decimal("1.1"), net_weight=Decimal("1.0"))
        session.add(product)
        session.flush()
        movement = InventoryMovement(
            company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="TRANSFER", from_location_id=source.id,
            to_location_id=target.id, quantity=Decimal("1"),
            weight=Decimal("1.0"), weight_unit_code="QIAN",
            occurred_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
        )
        session.add(movement)
        session.commit()
        assert session.query(InventoryMovement).count() == 1
        assert movement.from_location_id == source.id
        assert movement.to_location_id == target.id
    finally:
        session.close()
        engine.dispose()


def test_transfer_requires_two_distinct_locations():
    engine, session = setup_session()
    try:
        company = Company(code="JEWEL", name="測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        location = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        session.add(location)
        session.flush()
        product = Product(company_id=company.id, product_code="G00R-00003", name="戒指",
                          gross_weight=Decimal("1"), net_weight=Decimal("1"))
        session.add(product)
        session.flush()
        session.add(InventoryMovement(
            company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="TRANSFER", from_location_id=location.id,
            to_location_id=location.id, quantity=Decimal("1"),
        ))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.close()
        engine.dispose()


def test_product_and_inventory_tables_registered():
    assert {"product_categories", "products", "inventory_movements"} <= set(Base.metadata.tables)
