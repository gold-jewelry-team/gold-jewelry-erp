from decimal import Decimal
from uuid import uuid4

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


def test_transfer_keeps_exact_weight_unit_and_reference_while_conserving_quantity():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="WEIGHT-XFER", name="重量調撥測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        source = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        target = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        product = Product(company_id=company.id, product_code="XFER-001", name="重量調撥商品")
        session.add_all([source, target, product])
        session.flush()
        reference_id = uuid4()

        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("2"), to_location_id=source.id,
            weight=Decimal("1.2345"), weight_unit_code="QIAN",
        )
        movement = create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="TRANSFER", quantity=Decimal("1"),
            from_location_id=source.id, to_location_id=target.id,
            weight=Decimal("0.6172"), weight_unit_code="QIAN",
            reference_type="MANUAL_TRANSFER", reference_id=reference_id,
        )
        session.commit()

        stored = session.get(InventoryMovement, movement.id)
        assert stored.from_location_id == source.id
        assert stored.to_location_id == target.id
        assert stored.weight == Decimal("0.6172")
        assert stored.weight_unit_code == "QIAN"
        assert stored.reference_type == "MANUAL_TRANSFER"
        assert stored.reference_id == reference_id
        assert get_stock_balance(session, product_id=product.id, location_id=source.id) == Decimal("1")
        assert get_stock_balance(session, product_id=product.id, location_id=target.id) == Decimal("1")
        assert (
            get_stock_balance(session, product_id=product.id, location_id=source.id)
            + get_stock_balance(session, product_id=product.id, location_id=target.id)
        ) == Decimal("2")
    finally:
        session.close()
        engine.dispose()
