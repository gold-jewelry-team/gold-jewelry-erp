from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.product import Product
from app.services.inventory import create_inventory_movement, get_stock_balance


def setup_inventory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    company = Company(code="STORE", name="測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
    safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    session.add_all([show, safe])
    session.flush()
    product = Product(company_id=company.id, product_code="G00R-00010", name="黃金戒指",
                      gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"))
    session.add(product)
    session.flush()
    return engine, session, company, site, show, safe, product


def test_inventory_balance_is_derived_from_receipt_sale_and_transfer():
    engine, session, company, site, show, safe, product = setup_inventory()
    try:
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("3"), to_location_id=show.id,
        )
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="TRANSFER", quantity=Decimal("1"),
            from_location_id=show.id, to_location_id=safe.id,
        )
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="SALE", quantity=Decimal("1"), from_location_id=show.id,
        )
        session.commit()
        assert get_stock_balance(session, product_id=product.id, location_id=show.id) == Decimal("1")
        assert get_stock_balance(session, product_id=product.id, location_id=safe.id) == Decimal("1")
    finally:
        session.close()
        engine.dispose()


def test_inventory_service_rejects_location_from_another_site():
    engine, session, company, site, show, safe, product = setup_inventory()
    try:
        other_site = Site(company_id=company.id, code="BR2", name="二店")
        session.add(other_site)
        session.flush()
        other_location = StorageLocation(site_id=other_site.id, code="SAFE", name="二店保險櫃", location_type="SAFE")
        session.add(other_location)
        session.flush()
        with pytest.raises(ValueError, match="不屬於指定據點"):
            create_inventory_movement(
                session, company_id=company.id, site_id=site.id, product_id=product.id,
                movement_type="RECEIPT", quantity=Decimal("1"), to_location_id=other_location.id,
            )
    finally:
        session.close()
        engine.dispose()


def test_inventory_service_rejects_wrong_movement_direction():
    engine, session, company, site, show, safe, product = setup_inventory()
    try:
        with pytest.raises(ValueError, match="目的儲存位置"):
            create_inventory_movement(
                session, company_id=company.id, site_id=site.id, product_id=product.id,
                movement_type="RECEIPT", quantity=Decimal("1"), from_location_id=show.id,
            )
    finally:
        session.close()
        engine.dispose()


def test_inventory_balance_can_be_read_as_of_timestamp():
    engine, session, company, site, show, safe, product = setup_inventory()
    try:
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("2"), to_location_id=show.id,
            occurred_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="SALE", quantity=Decimal("1"), from_location_id=show.id,
            occurred_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
        )
        session.commit()
        assert get_stock_balance(
            session, product_id=product.id, location_id=show.id,
            as_of=datetime(2026, 11, 1, 12, tzinfo=timezone.utc),
        ) == Decimal("2")
    finally:
        session.close()
        engine.dispose()
