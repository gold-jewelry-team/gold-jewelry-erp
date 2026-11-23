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
from app.services.purchasing import receive_purchase_line


def test_label_lots_return_one_row_per_partial_receipt_with_exact_weight():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="LABEL-PARTIAL", name="分批標籤測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
    safe = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    show = StorageLocation(site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR")
    product = Product(company_id=company.id, product_code="LABEL-P-001", barcode="LABEL-P-001", name="分批入庫戒指")
    db.add_all([site, supplier, safe, show, product])
    db.flush()
    purchase = Purchase(company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                        purchase_no="PO-LABEL-PARTIAL", order_date=date(2026, 11, 23), status="ORDERED")
    db.add(purchase)
    db.flush()
    line = PurchaseLine(purchase_id=purchase.id, product_id=product.id, quantity=Decimal("3"),
                        received_quantity=Decimal("0"), weight=Decimal("1.0000"),
                        weight_unit_code="QIAN", unit_cost=Decimal("12000"))
    db.add(line)
    db.flush()
    first = receive_purchase_line(db, purchase_id=purchase.id, purchase_line_id=line.id,
                                  location_id=safe.id, received_quantity=Decimal("1"))
    second = receive_purchase_line(db, purchase_id=purchase.id, purchase_line_id=line.id,
                                   location_id=show.id, received_quantity=Decimal("2"))
    db.commit()
    company_id, product_id = company.id, product.id
    first_id, second_id = str(first.id), str(second.id)
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
        by_receipt = {lot["receipt_id"]: lot for lot in lots}
        assert set(by_receipt) == {first_id, second_id}
        assert by_receipt[first_id]["location_code"] == "SAFE"
        assert by_receipt[first_id]["received_quantity"] == "1.000"
        assert by_receipt[first_id]["weight"] == "0.3333"
        assert by_receipt[second_id]["location_code"] == "SHOW"
        assert by_receipt[second_id]["received_quantity"] == "2.000"
        assert by_receipt[second_id]["weight"] == "0.6667"
        assert sum((Decimal(lot["weight"]) for lot in lots), Decimal("0")) == Decimal("1.0000")
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
