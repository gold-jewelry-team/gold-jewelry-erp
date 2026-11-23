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


def test_receipt_cannot_put_stock_into_location_from_another_site():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="INV-SITE", name="據點隔離測試")
        session.add(company)
        session.flush()
        main = Site(company_id=company.id, code="MAIN", name="總店")
        branch = Site(company_id=company.id, code="BRANCH", name="分店")
        session.add_all([main, branch])
        session.flush()
        product = Product(company_id=company.id, product_code="INV-SITE-001", name="測試戒指")
        location = StorageLocation(site_id=branch.id, code="SAFE", name="分店保險櫃", location_type="SAFE")
        session.add_all([product, location])
        session.flush()

        with pytest.raises(ValueError, match="儲存位置不存在、未啟用或不屬於指定據點"):
            create_inventory_movement(
                session, company_id=company.id, site_id=main.id, product_id=product.id,
                movement_type="RECEIPT", quantity=Decimal("1"), to_location_id=location.id,
            )
        assert session.query(models.InventoryMovement).count() == 0
    finally:
        session.close()
        engine.dispose()
