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


def test_linear_and_qr_labels_use_product_code_when_barcode_is_missing():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BAR-FALLBACK", name="條碼備援測試")
    db.add(company)
    db.flush()
    product = Product(company_id=company.id, product_code="G00E-22618", barcode=None,
                      name="黃金耳環", gross_weight=Decimal("1.2000"),
                      net_weight=Decimal("1.0000"), weight_unit_code="QIAN")
    db.add(product)
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
        linear = client.get(f"/companies/{company_id}/products/{product_id}/barcode.svg")
        assert linear.status_code == 200, linear.text
        assert linear.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in linear.text
        qr = client.get(f"/companies/{company_id}/products/{product_id}/qr.svg")
        assert qr.status_code == 200, qr.text
        assert qr.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in qr.text
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
