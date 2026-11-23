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


def test_multi_line_purchase_stays_partial_until_every_line_is_fully_received():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="PO-MULTI-PARTIAL", name="多明細部分驗收狀態測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
        session.add_all([site, supplier])
        session.flush()
        safe = StorageLocation(
            site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
        )
        ring = Product(
            company_id=company.id, product_code="PO-MP-RING", name="黃金戒指"
        )
        bracelet = Product(
            company_id=company.id, product_code="PO-MP-BRACELET", name="黃金手鍊"
        )
        session.add_all([safe, ring, bracelet])
        session.flush()
        purchase = Purchase(
            company_id=company.id, site_id=site.id, supplier_id=supplier.id,
            purchase_no="PO-MULTI-PARTIAL-001",
            order_date=date(2026, 11, 23), status="ORDERED",
        )
        session.add(purchase)
        session.flush()
        ring_line = PurchaseLine(
            purchase_id=purchase.id, product_id=ring.id,
            quantity=Decimal("2"), received_quantity=Decimal("0"),
            weight=Decimal("1.0000"), weight_unit_code="QIAN",
            unit_cost=Decimal("12000.00"),
        )
        bracelet_line = PurchaseLine(
            purchase_id=purchase.id, product_id=bracelet.id,
            quantity=Decimal("3"), received_quantity=Decimal("0"),
            weight=Decimal("1.5000"), weight_unit_code="QIAN",
            unit_cost=Decimal("18000.00"),
        )
        session.add_all([ring_line, bracelet_line])
        session.flush()

        receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=ring_line.id,
            location_id=safe.id, received_quantity=Decimal("2"),
        )
        receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=bracelet_line.id,
            location_id=safe.id, received_quantity=Decimal("1"),
        )
        session.flush()

        assert ring_line.received_quantity == Decimal("2")
        assert bracelet_line.received_quantity == Decimal("1")
        assert purchase.status == "PARTIALLY_RECEIVED"

        receive_purchase_line(
            session, purchase_id=purchase.id, purchase_line_id=bracelet_line.id,
            location_id=safe.id, received_quantity=Decimal("2"),
        )
        session.commit()

        assert bracelet_line.received_quantity == Decimal("3")
        assert purchase.status == "RECEIVED"
        movements = session.query(InventoryMovement).filter(
            InventoryMovement.reference_type == "PURCHASE_LINE",
            InventoryMovement.reference_id.in_([ring_line.id, bracelet_line.id]),
        ).all()
        by_line = {}
        for movement in movements:
            by_line.setdefault(movement.reference_id, []).append(movement)
        assert len(by_line[ring_line.id]) == 1
        assert by_line[ring_line.id][0].quantity == Decimal("2")
        assert by_line[ring_line.id][0].weight == Decimal("1.0000")
        assert len(by_line[bracelet_line.id]) == 2
        assert sum(
            (movement.quantity for movement in by_line[bracelet_line.id]),
            Decimal("0"),
        ) == Decimal("3")
        assert sum(
            (movement.weight for movement in by_line[bracelet_line.id]),
            Decimal("0"),
        ) == Decimal("1.5000")
    finally:
        session.close()
        engine.dispose()
