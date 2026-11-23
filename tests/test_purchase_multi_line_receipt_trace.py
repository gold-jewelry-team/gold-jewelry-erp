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


def test_two_product_lines_in_one_purchase_keep_independent_receipt_references():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="MULTI", name="多商品採購追溯")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
        session.add_all([site, supplier])
        session.flush()
        safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        ring = Product(company_id=company.id, product_code="G-RING-001", name="黃金戒指")
        necklace = Product(company_id=company.id, product_code="G-NECK-001", name="黃金項鍊")
        session.add_all([safe, ring, necklace])
        session.flush()
        purchase = Purchase(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            purchase_no="PO-MULTI-001", order_date=date(2026, 11, 23), status="ORDERED",
        )
        session.add(purchase)
        session.flush()
        ring_line = PurchaseLine(
            purchase_id=purchase.id, product_id=ring.id, quantity=Decimal("2"),
            received_quantity=Decimal("0"), weight=Decimal("1.0000"),
            weight_unit_code="QIAN", unit_cost=Decimal("12000"),
        )
        necklace_line = PurchaseLine(
            purchase_id=purchase.id, product_id=necklace.id, quantity=Decimal("1"),
            received_quantity=Decimal("0"), weight=Decimal("2.5000"),
            weight_unit_code="QIAN", unit_cost=Decimal("30000"),
        )
        session.add_all([ring_line, necklace_line])
        session.flush()

        receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=ring_line.id,
            location_id=safe.id, received_quantity=Decimal("2"),
        )
        receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=necklace_line.id,
            location_id=safe.id, received_quantity=Decimal("1"),
        )
        session.commit()

        movements = session.query(InventoryMovement).filter(
            InventoryMovement.reference_type == "PURCHASE_LINE",
            InventoryMovement.reference_id.in_([ring_line.id, necklace_line.id]),
        ).all()
        by_reference = {row.reference_id: row for row in movements}
        assert set(by_reference) == {ring_line.id, necklace_line.id}
        assert by_reference[ring_line.id].product_id == ring.id
        assert by_reference[ring_line.id].quantity == Decimal("2")
        assert by_reference[ring_line.id].weight == Decimal("1.0000")
        assert by_reference[necklace_line.id].product_id == necklace.id
        assert by_reference[necklace_line.id].quantity == Decimal("1")
        assert by_reference[necklace_line.id].weight == Decimal("2.5000")
        assert all(row.to_location_id == safe.id for row in movements)
        assert purchase.status == "RECEIVED"
    finally:
        session.close()
        engine.dispose()
