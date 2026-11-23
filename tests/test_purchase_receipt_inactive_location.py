from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.services.purchasing import receive_purchase_line


def test_receiving_into_inactive_location_is_rejected_without_partial_receipt():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="INACTIVE", name="停用位置驗收測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
        session.add_all([site, supplier])
        session.flush()
        inactive_safe = StorageLocation(
            site_id=site.id, code="OLD-SAFE", name="已停用保險櫃",
            location_type="SAFE", is_active=False,
        )
        product = Product(company_id=company.id, product_code="G-INACTIVE-001", name="測試商品")
        session.add_all([inactive_safe, product])
        session.flush()
        purchase = Purchase(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            purchase_no="PO-INACTIVE-001", order_date=date(2026, 11, 23), status="ORDERED",
        )
        session.add(purchase)
        session.flush()
        line = PurchaseLine(
            purchase_id=purchase.id, product_id=product.id,
            quantity=Decimal("2"), received_quantity=Decimal("0"),
            weight=Decimal("1.0000"), weight_unit_code="QIAN",
            unit_cost=Decimal("10000"),
        )
        session.add(line)
        session.commit()

        with pytest.raises(ValueError, match="未啟用"):
            receive_purchase_line(
                session, purchase_id=purchase.id, purchase_line_id=line.id,
                location_id=inactive_safe.id, received_quantity=Decimal("1"),
            )
        session.rollback()

        assert session.query(InventoryMovement).count() == 0
        session.refresh(line)
        session.refresh(purchase)
        assert line.received_quantity == Decimal("0")
        assert purchase.status == "ORDERED"
    finally:
        session.close()
        engine.dispose()
