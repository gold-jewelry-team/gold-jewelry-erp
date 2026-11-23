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
from app.routers import product_master


def test_other_company_cannot_lookup_or_render_another_company_product():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="PRODUCT-OWNER", name="商品所屬公司")
    other = Company(code="PRODUCT-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    product = Product(company_id=owner.id, product_code="OWNER-G-001", barcode="OWNER-BAR-001",
                      name="公司甲商品", gross_weight=Decimal("1.2000"),
                      net_weight=Decimal("1.0000"), weight_unit_code="QIAN")
    db.add(product)
    db.commit()
    owner_id, other_id, product_id = owner.id, other.id, product.id
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
        lookup = client.get(f"/companies/{other_id}/products/lookup", params={"code": "OWNER-BAR-001"})
        assert lookup.status_code == 404
        lots = client.get(f"/companies/{other_id}/products/{product_id}/label-lots")
        assert lots.status_code == 404
        qr = client.get(f"/companies/{other_id}/products/{product_id}/qr.svg")
        assert qr.status_code == 404
        linear = client.get(f"/companies/{other_id}/products/{product_id}/barcode.svg")
        assert linear.status_code == 404
        own = client.get(f"/companies/{owner_id}/products/lookup", params={"code": "OWNER-BAR-001"})
        assert own.status_code == 200, own.text
        assert own.json()["id"] == str(product_id)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
