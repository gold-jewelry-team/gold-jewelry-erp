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
from app.services.inventory import create_inventory_movement, get_stock_balance
from app.services.purchasing import receive_purchase_line


def test_purchase_receipts_and_location_transfer_reconcile_quantity_and_weight():
    """A multi-step receiving/transfer ledger must conserve physical stock."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="LIFE-206", name="進貨調撥對帳測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-206", name="測試供應商")
        session.add_all([site, supplier])
        session.flush()

        safe = StorageLocation(
            site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
        )
        display = StorageLocation(
            site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
        )
        product = Product(
            company_id=company.id,
            product_code="LIFE-206-001",
            name="進貨調撥對帳戒指",
        )
        session.add_all([safe, display, product])
        session.flush()

        purchase = Purchase(
            company_id=company.id,
            site_id=site.id,
            supplier_id=supplier.id,
            purchase_no="PO-LIFE-206",
            order_date=date(2026, 11, 23),
            status="ORDERED",
        )
        session.add(purchase)
        session.flush()
        line = PurchaseLine(
            purchase_id=purchase.id,
            product_id=product.id,
            quantity=Decimal("3"),
            received_quantity=Decimal("0"),
            weight=Decimal("1.0000"),
            weight_unit_code="QIAN",
            unit_cost=Decimal("12000"),
        )
        session.add(line)
        session.flush()

        # Receive the same purchase line in two separate deliveries.
        first = receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=line.id,
            location_id=safe.id, received_quantity=Decimal("1"),
        )
        second = receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=line.id,
            location_id=safe.id, received_quantity=Decimal("2"),
        )
        session.commit()

        assert purchase.status == "RECEIVED"
        assert line.received_quantity == Decimal("3")
        assert [first.weight, second.weight] == [
            Decimal("0.3333"), Decimal("0.6667")
        ]
        assert get_stock_balance(
            session, product_id=product.id, location_id=safe.id
        ) == Decimal("3")

        # Move one item and its proportional weight from safe to display.
        transfer = create_inventory_movement(
            session,
            company_id=company.id,
            site_id=site.id,
            product_id=product.id,
            movement_type="TRANSFER",
            quantity=Decimal("1"),
            from_location_id=safe.id,
            to_location_id=display.id,
            weight=Decimal("0.3333"),
            weight_unit_code="QIAN",
            reference_type="MANUAL_TRANSFER",
        )
        session.commit()

        movements = session.query(InventoryMovement).filter_by(
            product_id=product.id
        ).all()
        receipts = [m for m in movements if m.movement_type == "RECEIPT"]
        assert {m.id for m in receipts} == {first.id, second.id}
        assert transfer in movements
        assert len(receipts) == 2
        assert sum((m.quantity for m in receipts), Decimal("0")) == Decimal("3")
        assert sum((m.weight for m in receipts), Decimal("0")) == Decimal("1.0000")

        safe_quantity = get_stock_balance(
            session, product_id=product.id, location_id=safe.id
        )
        display_quantity = get_stock_balance(
            session, product_id=product.id, location_id=display.id
        )
        assert safe_quantity == Decimal("2")
        assert display_quantity == Decimal("1")
        assert safe_quantity + display_quantity == Decimal("3")

        # Ledger-derived weight must also reconcile: receipt weight less the
        # transfer out at SAFE, and the same transferred weight at SHOW.
        safe_net_weight = sum(
            (
                (m.weight or Decimal("0"))
                * (
                    Decimal("1") if m.to_location_id == safe.id
                    else Decimal("-1") if m.from_location_id == safe.id
                    else Decimal("0")
                )
                for m in movements
            ),
            Decimal("0"),
        )
        display_net_weight = sum(
            (
                (m.weight or Decimal("0"))
                * (
                    Decimal("1") if m.to_location_id == display.id
                    else Decimal("-1") if m.from_location_id == display.id
                    else Decimal("0")
                )
                for m in movements
            ),
            Decimal("0"),
        )
        assert safe_net_weight == Decimal("0.6667")
        assert display_net_weight == Decimal("0.3333")
        assert safe_net_weight + display_net_weight == Decimal("1.0000")
    finally:
        session.close()
        engine.dispose()
