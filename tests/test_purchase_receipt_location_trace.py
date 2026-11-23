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
from app.services.inventory import get_stock_balance
from app.services.purchasing import receive_purchase_line


def test_partial_purchase_receipts_at_two_locations_keep_lineage_and_separate_stock():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="TRACE", name="驗收追溯測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
        session.add_all([site, supplier])
        session.flush()
        safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
        product = Product(company_id=company.id, product_code="G-TRACE-001", name="追溯測試戒指")
        session.add_all([safe, show, product])
        session.flush()
        purchase = Purchase(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            purchase_no="PO-TRACE-001", order_date=date(2026, 11, 23), status="ORDERED",
        )
        session.add(purchase)
        session.flush()
        line = PurchaseLine(
            purchase_id=purchase.id, product_id=product.id,
            quantity=Decimal("2"), received_quantity=Decimal("0"),
            weight=Decimal("1.2000"), weight_unit_code="QIAN",
            unit_cost=Decimal("10000"),
        )
        session.add(line)
        session.flush()

        first = receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=line.id,
            location_id=safe.id, received_quantity=Decimal("1"),
        )
        second = receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=line.id,
            location_id=show.id, received_quantity=Decimal("1"),
        )
        session.commit()

        rows = session.query(InventoryMovement).filter(
            InventoryMovement.reference_type == "PURCHASE_LINE",
            InventoryMovement.reference_id == line.id,
        ).all()
        assert {row.id for row in rows} == {first.id, second.id}
        assert all(row.product_id == product.id for row in rows)
        assert all(row.site_id == site.id for row in rows)
        assert {row.to_location_id for row in rows} == {safe.id, show.id}
        assert sum((row.quantity for row in rows), Decimal("0")) == Decimal("2")
        assert sum((row.weight for row in rows), Decimal("0")) == Decimal("1.2000")
        assert get_stock_balance(session, product_id=product.id, location_id=safe.id) == Decimal("1")
        assert get_stock_balance(session, product_id=product.id, location_id=show.id) == Decimal("1")
        assert line.received_quantity == Decimal("2")
        assert purchase.status == "RECEIVED"
    finally:
        session.close()
        engine.dispose()
