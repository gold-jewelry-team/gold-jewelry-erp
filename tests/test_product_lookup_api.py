import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.routers.product_master import get_db as product_master_get_db
from app.routers.company_setup import get_db as company_setup_get_db

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_database():
    app.dependency_overrides[company_setup_get_db] = override_get_db
    app.dependency_overrides[product_master_get_db] = override_get_db
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        app.dependency_overrides.pop(company_setup_get_db, None)
        app.dependency_overrides.pop(product_master_get_db, None)


def test_exact_scan_lookup_accepts_barcode_and_product_code():
    company = client.post("/companies", json={"code": "SCAN", "name": "掃描測試銀樓"}).json()
    company_id = company["id"]
    product = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-00001", "barcode": "471000000001", "name": "測試戒指"},
    )
    assert product.status_code == 201

    by_barcode = client.get(
        f"/companies/{company_id}/products/lookup", params={"code": "471000000001"}
    )
    assert by_barcode.status_code == 200
    assert by_barcode.json()["id"] == product.json()["id"]

    by_product_code = client.get(
        f"/companies/{company_id}/products/lookup", params={"code": "G00R-00001"}
    )
    assert by_product_code.status_code == 200
    assert by_product_code.json()["product_code"] == "G00R-00001"


def test_exact_scan_lookup_rejects_unknown_and_inactive_products():
    company_id = client.post(
        "/companies", json={"code": "SCAN2", "name": "掃描測試銀樓二"}
    ).json()["id"]
    product = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-00002", "barcode": "471000000002", "name": "停用戒指"},
    ).json()
    assert client.patch(
        f"/companies/{company_id}/products/{product['id']}", json={"is_active": False}
    ).status_code == 200

    unknown = client.get(
        f"/companies/{company_id}/products/lookup", params={"code": "999999"}
    )
    inactive = client.get(
        f"/companies/{company_id}/products/lookup", params={"code": "471000000002"}
    )
    assert unknown.status_code == 404
    assert inactive.status_code == 404


def test_product_qr_svg_encodes_barcode_or_product_code():
    company_id = client.post(
        "/companies", json={"code": "QR", "name": "QR 標籤測試銀樓"}
    ).json()["id"]
    with_barcode = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-QR001", "barcode": "471000000901", "name": "有條碼戒指"},
    ).json()
    without_barcode = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-QR002", "name": "使用商品編號的戒指"},
    ).json()

    barcode_qr = client.get(
        f"/companies/{company_id}/products/{with_barcode['id']}/qr.svg"
    )
    code_qr = client.get(
        f"/companies/{company_id}/products/{without_barcode['id']}/qr.svg"
    )
    assert barcode_qr.status_code == 200
    assert barcode_qr.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in barcode_qr.text
    assert code_qr.status_code == 200
    assert "<svg" in code_qr.text

    missing = client.get(
        f"/companies/{company_id}/products/00000000-0000-0000-0000-000000000000/qr.svg"
    )
    assert missing.status_code == 404
