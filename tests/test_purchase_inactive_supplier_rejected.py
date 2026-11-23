from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.site import Site
from app.models.supplier import Supplier
from app.routers import purchases


def test_purchase_creation_rejects_inactive_supplier_without_creating_order():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="PO-INACTIVE-SUP", name="停用供應商採購測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(
        company_id=company.id, code="SUP-OFF", name="已停用供應商", is_active=False
    )
    product = Product(
        company_id=company.id, product_code="PO-INACTIVE-SUP-001", name="黃金手鍊"
    )
    db.add_all([site, supplier, product])
    db.commit()
    company_id, site_id, supplier_id, product_id = (
        company.id, site.id, supplier.id, product.id
    )
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
        response = client.post(f"/companies/{company_id}/purchases", json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_no": "PO-INACTIVE-SUP-001",
            "order_date": date(2026, 11, 23).isoformat(),
            "currency_code": "TWD",
            "lines": [{
                "product_id": str(product_id), "quantity": "1",
                "weight": "0.8500", "weight_unit_code": "QIAN",
                "unit_cost": "10000.00",
            }],
        })
        assert response.status_code == 422, response.text
        assert "供應商不存在、未啟用或不屬於指定公司" in response.json()["detail"]

        check = TestSession()
        try:
            assert check.query(Purchase).filter_by(
                company_id=company_id, purchase_no="PO-INACTIVE-SUP-001"
            ).count() == 0
        finally:
            check.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
