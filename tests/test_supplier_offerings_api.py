from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.product import Product, ProductCategory
from app.models.supplier import Supplier
from app.models.supplier_offering import SupplierCategoryOffering, SupplierProductOffering
from app.routers import company_setup, product_master, supplier_offerings, suppliers


def _context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    company = Company(code="SO-TEST", name="廠商供貨測試")
    session.add(company)
    session.flush()
    category = ProductCategory(company_id=company.id, code="WOMENS_RING", name="女戒")
    supplier_a = Supplier(company_id=company.id, code="SUP-A", name="甲廠商")
    supplier_b = Supplier(company_id=company.id, code="SUP-B", name="乙廠商")
    session.add_all([category, supplier_a, supplier_b])
    session.flush()
    product = Product(
        company_id=company.id, category_id=category.id,
        product_code="G00R-90001", name="女戒測試款",
    )
    session.add(product)
    session.commit()
    ids = (company.id, category.id, supplier_a.id, supplier_b.id, product.id)
    session.close()

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[company_setup.get_db] = override_db
    app.dependency_overrides[product_master.get_db] = override_db
    app.dependency_overrides[suppliers.get_db] = override_db
    app.dependency_overrides[supplier_offerings.get_db] = override_db
    return engine, Session, ids


def test_company_creation_seeds_all_fifteen_default_categories():
    engine, Session, _ids = _context()
    try:
        client = TestClient(app)
        response = client.post("/companies", json={"code": "NEW", "name": "新銀樓"})
        assert response.status_code == 201, response.text
        company_id = response.json()["id"]
        categories = client.get(f"/companies/{company_id}/product-categories")
        assert categories.status_code == 200
        names = [item["name"] for item in categories.json()]
        assert names == [
            "對戒", "女戒", "可調式尾戒", "固定圍尾戒", "開口式手環",
            "固定圍手環", "女墜", "男墜", "女手鏈", "男手鏈",
            "紅線", "耳環", "套鏈", "童手環", "小金塊",
        ]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_supplier_category_search_is_bidirectional_and_preferred_is_unique():
    engine, Session, (company_id, category_id, supplier_a_id, supplier_b_id, _product_id) = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        a = client.post(
            f"{base}/suppliers/{supplier_a_id}/category-offerings",
            json={"category_id": str(category_id), "is_preferred": True},
        )
        b = client.post(
            f"{base}/suppliers/{supplier_b_id}/category-offerings",
            json={"category_id": str(category_id), "is_preferred": True},
        )
        assert a.status_code == 201, a.text
        assert b.status_code == 201, b.text

        by_category = client.get(
            f"{base}/supplier-category-offerings",
            params={"category_id": str(category_id)},
        )
        assert by_category.status_code == 200
        assert len(by_category.json()) == 2
        assert sum(row["is_preferred"] for row in by_category.json()) == 1

        by_supplier = client.get(
            f"{base}/supplier-category-offerings",
            params={"supplier_id": str(supplier_b_id)},
        )
        assert by_supplier.status_code == 200
        assert len(by_supplier.json()) == 1
        assert by_supplier.json()[0]["supplier_id"] == str(supplier_b_id)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_product_offering_links_exact_product_and_auto_creates_category_offering():
    engine, Session, (company_id, category_id, supplier_a_id, _supplier_b_id, product_id) = _context()
    try:
        client = TestClient(app)
        base = f"/companies/{company_id}"
        created = client.post(
            f"{base}/suppliers/{supplier_a_id}/product-offerings",
            json={
                "product_id": str(product_id),
                "supplier_product_code": "VENDOR-RING-01",
                "quoted_unit_cost": "12500.00",
                "currency_code": "TWD",
                "min_order_quantity": "1",
                "lead_time_days": 7,
                "is_preferred": True,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["supplier_product_code"] == "VENDOR-RING-01"
        assert created.json()["quoted_unit_cost"] == "12500.00"

        exact_product_suppliers = client.get(
            f"{base}/products/{product_id}/supplier-offerings"
        )
        assert exact_product_suppliers.status_code == 200
        assert len(exact_product_suppliers.json()) == 1
        assert exact_product_suppliers.json()[0]["supplier_id"] == str(supplier_a_id)

        vendor_products = client.get(
            f"{base}/supplier-product-offerings",
            params={"supplier_id": str(supplier_a_id)},
        )
        assert vendor_products.status_code == 200
        assert len(vendor_products.json()) == 1
        assert vendor_products.json()[0]["product_id"] == str(product_id)
        exact_product_lookup = client.get(
            f"{base}/supplier-product-offerings",
            params={"product_id": str(product_id)},
        )
        assert exact_product_lookup.status_code == 200
        assert len(exact_product_lookup.json()) == 1
        assert exact_product_lookup.json()[0]["supplier_id"] == str(supplier_a_id)

        category_suppliers = client.get(
            f"{base}/supplier-category-offerings",
            params={"category_id": str(category_id)},
        )
        assert category_suppliers.status_code == 200
        assert len(category_suppliers.json()) == 1
        check = Session()
        assert check.query(SupplierProductOffering).count() == 1
        assert check.query(SupplierCategoryOffering).count() == 1
        check.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
