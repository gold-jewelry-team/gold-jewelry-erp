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
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.routers import product_master
from app.services.purchasing import receive_purchase_line


def test_label_lots_keep_same_product_purchase_and_supplier_batches_separate():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="LABEL-BATCH", name="標籤批次追溯")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier_a = Supplier(company_id=company.id, code="SUP-A", name="甲供應商")
    supplier_b = Supplier(company_id=company.id, code="SUP-B", name="乙供應商")
    safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
    product = Product(company_id=company.id, product_code="LABEL-G-001", barcode="LABEL-G-001",
                      name="同款黃金戒指", gross_weight=Decimal("1.2000"), net_weight=Decimal("1.0000"))
    db.add_all([site, supplier_a, supplier_b, safe, show, product])
    db.flush()
    purchases = []
    for number, supplier, location, weight in [
        ("PO-LABEL-A", supplier_a, safe, Decimal("1.0000")),
        ("PO-LABEL-B", supplier_b, show, Decimal("1.2500")),
    ]:
        purchase = Purchase(company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                            purchase_no=number, order_date=date(2026, 11, 23), status="ORDERED")
        db.add(purchase)
        db.flush()
        line = PurchaseLine(purchase_id=purchase.id, product_id=product.id, quantity=Decimal("1"),
                            received_quantity=Decimal("0"), weight=weight, weight_unit_code="QIAN",
                            unit_cost=Decimal("12000"))
        db.add(line)
        db.flush()
        purchases.append((purchase, line, location))
    for purchase, line, location in purchases:
        receive_purchase_line(db, purchase_id=purchase.id, purchase_line_id=line.id,
                              location_id=location.id, received_quantity=Decimal("1"))
    db.commit()
    company_id, product_id = company.id, product.id
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
        response = TestClient(app).get(f"/companies/{company_id}/products/{product_id}/label-lots")
        assert response.status_code == 200, response.text
        lots = response.json()
        assert len(lots) == 2
        by_purchase = {lot["purchase_no"]: lot for lot in lots}
        assert set(by_purchase) == {"PO-LABEL-A", "PO-LABEL-B"}
        assert by_purchase["PO-LABEL-A"]["supplier_name"] == "甲供應商"
        assert by_purchase["PO-LABEL-A"]["location_code"] == "SAFE"
        assert by_purchase["PO-LABEL-A"]["weight"] == "1.0000"
        assert by_purchase["PO-LABEL-B"]["supplier_name"] == "乙供應商"
        assert by_purchase["PO-LABEL-B"]["location_code"] == "SHOW"
        assert by_purchase["PO-LABEL-B"]["weight"] == "1.2500"
        assert all(lot["received_quantity"] == "1.000" for lot in lots)
        assert len({lot["receipt_id"] for lot in lots}) == 2
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
