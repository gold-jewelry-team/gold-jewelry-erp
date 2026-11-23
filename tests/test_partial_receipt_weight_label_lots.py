from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.routers import product_master
from app.services.inventory import get_stock_balance
from app.services.purchasing import receive_purchase_line


def test_partial_receipts_split_weight_exactly_and_keep_label_lots_by_location():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    company = Company(code="PARTIAL-RECEIPT", name="分批驗收入庫測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-PARTIAL", name="分批供應商")
    db.add_all([site, supplier])
    db.flush()
    safe = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    display = StorageLocation(
        site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
    )
    product = Product(
        company_id=company.id,
        product_code="PARTIAL-G-001",
        barcode="471000000333",
        name="分批驗收黃金戒指",
        gross_weight=Decimal("1.0000"),
        net_weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
    )
    db.add_all([safe, display, product])
    db.flush()

    purchase = Purchase(
        company_id=company.id,
        site_id=site.id,
        supplier_id=supplier.id,
        purchase_no="PO-PARTIAL-001",
        order_date=date(2026, 11, 23),
        currency_code="TWD",
        status="ORDERED",
    )
    db.add(purchase)
    db.flush()
    line = PurchaseLine(
        purchase_id=purchase.id,
        product_id=product.id,
        quantity=Decimal("3"),
        received_quantity=Decimal("0"),
        weight=Decimal("1.0000"),
        weight_unit_code="QIAN",
        unit_cost=Decimal("12000.00"),
    )
    db.add(line)
    db.flush()

    receipt_locations = [safe, display, safe]
    receipt_ids = []
    for location in receipt_locations:
        receipt = receive_purchase_line(
            db,
            purchase_id=purchase.id,
            purchase_line_id=line.id,
            location_id=location.id,
            received_quantity=Decimal("1"),
        )
        receipt_ids.append(receipt.id)

    assert purchase.status == "RECEIVED"
    assert line.received_quantity == Decimal("3")
    company_id, product_id, safe_id, display_id = (
        company.id, product.id, safe.id, display.id
    )
    db.commit()
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[product_master.get_db] = override_db
    try:
        client = TestClient(app)
        lots_response = client.get(
            f"/companies/{company_id}/products/{product_id}/label-lots"
        )
        assert lots_response.status_code == 200, lots_response.text
        lots = lots_response.json()
        assert len(lots) == 3
        assert {lot["receipt_id"] for lot in lots} == {
            str(receipt_id) for receipt_id in receipt_ids
        }
        assert sum(
            (Decimal(lot["weight"]) for lot in lots), Decimal("0")
        ) == Decimal("1.0000")
        assert sorted(Decimal(lot["weight"]) for lot in lots) == [
            Decimal("0.3333"), Decimal("0.3333"), Decimal("0.3334")
        ]
        assert all(lot["received_quantity"] == "1.000" for lot in lots)
        assert all(lot["purchase_no"] == "PO-PARTIAL-001" for lot in lots)
        assert sorted(lot["location_code"] for lot in lots) == [
            "SAFE", "SAFE", "SHOW"
        ]

        verify = TestSession()
        assert get_stock_balance(
            verify, product_id=product_id, location_id=safe_id
        ) == Decimal("2")
        assert get_stock_balance(
            verify, product_id=product_id, location_id=display_id
        ) == Decimal("1")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
