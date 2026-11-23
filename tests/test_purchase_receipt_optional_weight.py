from datetime import date
from decimal import Decimal

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


def test_receiving_purchase_line_without_declared_weight_keeps_weight_unknown():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="PO-NO-WEIGHT", name="未提供重量驗收測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
        session.add_all([site, supplier])
        session.flush()
        safe = StorageLocation(
            site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
        )
        product = Product(
            company_id=company.id, product_code="PO-NO-WEIGHT-001", name="待秤重商品"
        )
        session.add_all([safe, product])
        session.flush()
        purchase = Purchase(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            purchase_no="PO-NO-WEIGHT-001", order_date=date(2026, 11, 23),
            status="ORDERED",
        )
        session.add(purchase)
        session.flush()
        line = PurchaseLine(
            purchase_id=purchase.id, product_id=product.id,
            quantity=Decimal("2"), received_quantity=Decimal("0"),
            weight=None, weight_unit_code=None, unit_cost=Decimal("5000.00"),
        )
        session.add(line)
        session.flush()

        movement = receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=line.id,
            location_id=safe.id, received_quantity=Decimal("2"),
        )
        session.commit()

        assert movement.movement_type == "RECEIPT"
        assert movement.quantity == Decimal("2")
        assert movement.weight is None
        assert movement.weight_unit_code is None
        assert line.received_quantity == Decimal("2")
        assert purchase.status == "RECEIVED"
        movements = session.query(InventoryMovement).filter_by(
            reference_type="PURCHASE_LINE", reference_id=line.id
        ).all()
        assert len(movements) == 1
        assert movements[0].weight is None
    finally:
        session.close()
        engine.dispose()
