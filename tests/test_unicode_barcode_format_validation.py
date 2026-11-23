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


def test_unicode_barcode_can_render_qr_but_is_rejected_for_code128():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="BAR-UNICODE", name="Unicode 條碼測試")
    db.add(company)
    db.flush()
    product = Product(company_id=company.id, product_code="G00R-21663", barcode="黃金戒指-21663",
                      name="黃金戒指", gross_weight=Decimal("1.2000"),
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
        assert linear.status_code == 422
        assert linear.json()["detail"] == "條碼內容必須使用 ASCII 字元。"
        qr = client.get(f"/companies/{company_id}/products/{product_id}/qr.svg")
        assert qr.status_code == 200, qr.text
        assert "<svg" in qr.text
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
