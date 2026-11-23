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


def test_label_lots_limit_returns_requested_rows_and_rejects_out_of_range():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="LABEL-PAGE", name="標籤分頁測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP", name="供應商")
    db.add_all([site, supplier])
    db.flush()
    location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
    product = Product(company_id=company.id, product_code="LABEL-PAGE-001", barcode="LABEL-PAGE-001", name="分頁測試戒指")
    db.add_all([location, product])
    db.flush()
    purchase = Purchase(company_id=company.id, site_id=site.id, supplier_id=supplier.id,
                        purchase_no="PO-LABEL-PAGE", order_date=date(2026, 11, 23), status="ORDERED")
    db.add(purchase)
    db.flush()
    line = PurchaseLine(purchase_id=purchase.id, product_id=product.id, quantity=Decimal("2"),
                        received_quantity=Decimal("0"), weight=Decimal("2.0000"),
                        weight_unit_code="QIAN", unit_cost=Decimal("12000"))
    db.add(line)
    db.flush()
    receive_purchase_line(db, purchase_id=purchase.id, purchase_line_id=line.id,
                          location_id=location.id, received_quantity=Decimal("1"))
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
        client = TestClient(app)
        one = client.get(f"/companies/{company_id}/products/{product_id}/label-lots", params={"limit": 1})
        assert one.status_code == 200, one.text
        assert len(one.json()) == 1
        maximum = client.get(f"/companies/{company_id}/products/{product_id}/label-lots", params={"limit": 500})
        assert maximum.status_code == 200, maximum.text
        assert len(maximum.json()) == 2
        too_many = client.get(f"/companies/{company_id}/products/{product_id}/label-lots", params={"limit": 501})
        assert too_many.status_code == 422
        zero = client.get(f"/companies/{company_id}/products/{product_id}/label-lots", params={"limit": 0})
        assert zero.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
