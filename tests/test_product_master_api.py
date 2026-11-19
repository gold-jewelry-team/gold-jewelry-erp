import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.routers.product_master import get_db

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
def isolate_product_master_database():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def teardown_module():
    engine.dispose()


def setup_company():
    response = client.post("/companies", json={"code": "JEWEL", "name": "測試銀樓"})
    assert response.status_code == 201
    return response.json()["id"]


def test_category_and_product_create_list_update_flow():
    company_id = setup_company()
    category = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "RING", "name": "戒指", "sort_order": 10},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]

    duplicate_category = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "RING", "name": "重複戒指"},
    )
    assert duplicate_category.status_code == 409

    product = client.post(
        f"/companies/{company_id}/products",
        json={
            "category_id": category_id,
            "product_code": "G00R-22618",
            "barcode": "471000002618",
            "name": "黃金戒指",
            "gross_weight": "1.2500",
            "net_weight": "1.2000",
            "weight_unit_code": "QIAN",
            "labor_fee": "800",
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]

    listed = client.get(f"/companies/{company_id}/products", params={"q": "22618"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["category_id"] == category_id

    updated = client.patch(
        f"/companies/{company_id}/products/{product_id}",
        json={"name": "黃金戒指（改款）", "labor_fee": "900"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "黃金戒指（改款）"
    assert updated.json()["labor_fee"] == "900.00"


def test_product_rejects_foreign_category_and_invalid_weights():
    company_a = setup_company()
    company_b = client.post("/companies", json={"code": "OTHER", "name": "另一家公司"}).json()["id"]
    foreign_category = client.post(
        f"/companies/{company_b}/product-categories",
        json={"code": "RING", "name": "戒指"},
    ).json()["id"]

    foreign = client.post(
        f"/companies/{company_a}/products",
        json={"category_id": foreign_category, "product_code": "P-1", "name": "測試商品"},
    )
    assert foreign.status_code == 404

    invalid_weight = client.post(
        f"/companies/{company_a}/products",
        json={
            "product_code": "P-2", "name": "錯誤重量",
            "gross_weight": "1.0000", "net_weight": "1.1000",
        },
    )
    assert invalid_weight.status_code == 422


def test_product_code_and_barcode_are_unique_per_company():
    company_id = setup_company()
    payload = {"product_code": "G00R-00001", "barcode": "471000000001", "name": "戒指"}
    assert client.post(f"/companies/{company_id}/products", json=payload).status_code == 201
    duplicate_code = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-00001", "name": "另一件戒指"},
    )
    assert duplicate_code.status_code == 409
    duplicate_barcode = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-00002", "barcode": "471000000001", "name": "第三件戒指"},
    )
    assert duplicate_barcode.status_code == 409
