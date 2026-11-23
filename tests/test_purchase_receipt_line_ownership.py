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
from app.routers import purchases


def test_receiving_rejects_line_belonging_to_another_purchase_without_side_effects():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-LINE-SCOPE", name="採購明細歸屬測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
    db.add_all([site, supplier])
    db.flush()
    safe = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    product = Product(
        company_id=company.id, product_code="PO-SCOPE-001", name="黃金戒指"
    )
    db.add_all([safe, product])
    db.flush()

    first_purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-SCOPE-A", order_date=date(2026, 11, 23), status="ORDERED",
    )
    second_purchase = Purchase(
        company_id=company.id, site_id=site.id, supplier_id=supplier.id,
        purchase_no="PO-SCOPE-B", order_date=date(2026, 11, 23), status="ORDERED",
    )
    db.add_all([first_purchase, second_purchase])
    db.flush()
    first_line = PurchaseLine(
        purchase_id=first_purchase.id, product_id=product.id,
        quantity=Decimal("2"), received_quantity=Decimal("0"),
        weight=Decimal("1.0000"), weight_unit_code="QIAN",
        unit_cost=Decimal("12000"),
    )
    foreign_line = PurchaseLine(
        purchase_id=second_purchase.id, product_id=product.id,
        quantity=Decimal("3"), received_quantity=Decimal("0"),
        weight=Decimal("1.5000"), weight_unit_code="QIAN",
        unit_cost=Decimal("12000"),
    )
    db.add_all([first_line, foreign_line])
    db.commit()

    company_id = company.id
    first_purchase_id = first_purchase.id
    second_purchase_id = second_purchase.id
    first_line_id = first_line.id
    foreign_line_id = foreign_line.id
    safe_id = safe.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[purchases.get_db] = override_db
    try:
        client = TestClient(app)
        rejected = client.post(
            f"/companies/{company_id}/purchases/{first_purchase_id}/receive",
            json={
                "purchase_line_id": str(foreign_line_id),
                "location_id": str(safe_id),
                "received_quantity": "1",
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert "採購明細不存在" in rejected.json()["detail"]

        check = TestSession()
        try:
            first = check.get(Purchase, first_purchase_id)
            second = check.get(Purchase, second_purchase_id)
            first_detail = check.get(PurchaseLine, first_line_id)
            foreign_detail = check.get(PurchaseLine, foreign_line_id)
            assert first.status == "ORDERED"
            assert second.status == "ORDERED"
            assert first_detail.received_quantity == Decimal("0")
            assert foreign_detail.received_quantity == Decimal("0")
            assert check.query(InventoryMovement).count() == 0
        finally:
            check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
