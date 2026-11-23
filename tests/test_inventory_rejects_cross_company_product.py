from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.product import Product
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.services.inventory import create_inventory_movement


def test_inventory_movement_cannot_use_product_owned_by_another_company():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        owner = Company(code="INV-OWNER", name="商品所屬公司")
        other = Company(code="INV-OTHER", name="異動指定公司")
        session.add_all([owner, other])
        session.flush()
        site = Site(company_id=other.id, code="MAIN", name="總店")
        product = Product(company_id=owner.id, product_code="OWNER-001", name="甲公司商品")
        session.add_all([site, product])
        session.flush()
        location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        session.add(location)
        session.flush()

        with pytest.raises(ValueError, match="商品不存在或不屬於指定公司"):
            create_inventory_movement(
                session, company_id=other.id, site_id=site.id, product_id=product.id,
                movement_type="RECEIPT", quantity=Decimal("1"), to_location_id=location.id,
            )
        assert session.query(models.InventoryMovement).count() == 0
    finally:
        session.close()
        engine.dispose()
