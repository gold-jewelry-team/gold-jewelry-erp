from datetime import date
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
from app.models.supplier import Supplier
from app.models.purchase import Purchase, PurchaseLine
from app.models.inventory import InventoryMovement
from app.services.purchasing import receive_purchase_line
from app.services.inventory import get_stock_balance


def setup_purchase():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    company = Company(code="STORE", name="測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    session.add_all([site, supplier])
    session.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code="G00R-00020", name="黃金戒指",
                      gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"))
    session.add_all([location, product])
    session.flush()
    purchase = Purchase(company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                        purchase_no="PO-20261119-001", order_date=date(2026, 11, 19), status="ORDERED")
    session.add(purchase)
    session.flush()
    line = PurchaseLine(purchase_id=purchase.id, product_id=product.id,
                        quantity=Decimal("3"), received_quantity=Decimal("0"),
                        weight=Decimal("1.1"), weight_unit_code="QIAN", unit_cost=Decimal("12000"))
    session.add(line)
    session.flush()
    return engine, session, company, site, supplier, location, product, purchase, line


def test_receiving_creates_inventory_movement_and_updates_received_quantity():
    engine, session, company, site, supplier, location, product, purchase, line = setup_purchase()
    try:
        movement = receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=line.id,
            location_id=location.id, received_quantity=Decimal("2"),
        )
        session.commit()
        assert movement.movement_type == "RECEIPT"
        assert line.received_quantity == Decimal("2")
        assert purchase.status == "PARTIALLY_RECEIVED"
        assert get_stock_balance(session, product_id=product.id, location_id=location.id) == Decimal("2")
    finally:
        session.close()
        engine.dispose()


def test_receiving_remaining_quantity_marks_purchase_received():
    engine, session, company, site, supplier, location, product, purchase, line = setup_purchase()
    try:
        receive_purchase_line(session, purchase_id=purchase.id, purchase_line_id=line.id,
                              location_id=location.id, received_quantity=Decimal("3"))
        session.commit()
        assert line.received_quantity == Decimal("3")
        assert purchase.status == "RECEIVED"
    finally:
        session.close()
        engine.dispose()


def test_receiving_cannot_exceed_ordered_quantity():
    engine, session, company, site, supplier, location, product, purchase, line = setup_purchase()
    try:
        with pytest.raises(ValueError, match="超過"):
            receive_purchase_line(session, purchase_id=purchase.id, purchase_line_id=line.id,
                                  location_id=location.id, received_quantity=Decimal("4"))
    finally:
        session.close()
        engine.dispose()


def test_receiving_rejects_location_from_another_site():
    engine, session, company, site, supplier, location, product, purchase, line = setup_purchase()
    try:
        other_site = Site(company_id=company.id, code="BR2", name="二店")
        session.add(other_site)
        session.flush()
        other_location = StorageLocation(site_id=other_site.id, code="SAFE", name="二店保險櫃", location_type="SAFE")
        session.add(other_location)
        session.flush()
        with pytest.raises(ValueError, match="不屬於採購據點"):
            receive_purchase_line(session, purchase_id=purchase.id, purchase_line_id=line.id,
                                  location_id=other_location.id, received_quantity=Decimal("1"))
    finally:
        session.close()
        engine.dispose()
