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
from app.models.purchase import Purchase, PurchaseLine
from app.models.product import Product
from app.models.site import Site
from app.models.supplier import Supplier
from app.routers import purchases


def test_duplicate_purchase_number_returns_conflict_without_creating_partial_order():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-DUP-API", name="採購單號重複測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="供應商")
    product = Product(company_id=company.id, product_code="PO-DUP-001", name="黃金戒指")
    db.add_all([site, supplier, product])
    db.commit()
    company_id, site_id, supplier_id, product_id = company.id, site.id, supplier.id, product.id
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
        payload = {
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_no": "PO-DUPLICATE-001",
            "order_date": date(2026, 11, 23).isoformat(),
            "currency_code": "TWD",
            "lines": [{
                "product_id": str(product_id), "quantity": "2",
                "weight": "1.2500", "weight_unit_code": "QIAN",
                "unit_cost": "12000.00", "cost_labor_fee": "300.00",
            }],
        }
        first = client.post(f"/companies/{company_id}/purchases", json=payload)
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]

        duplicate_payload = {**payload, "lines": [{
            **payload["lines"][0], "quantity": "9", "weight": "9.9999",
        }]}
        duplicate = client.post(
            f"/companies/{company_id}/purchases", json=duplicate_payload
        )
        assert duplicate.status_code == 409, duplicate.text

        check = TestSession()
        try:
            orders = check.query(Purchase).filter_by(
                company_id=company_id, purchase_no="PO-DUPLICATE-001"
            ).all()
            assert len(orders) == 1
            assert str(orders[0].id) == first_id
            lines = check.query(PurchaseLine).filter_by(purchase_id=orders[0].id).all()
            assert len(lines) == 1
            assert lines[0].quantity == Decimal("2")
            assert lines[0].weight == Decimal("1.2500")
            assert lines[0].unit_cost == Decimal("12000.00")
        finally:
            check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
