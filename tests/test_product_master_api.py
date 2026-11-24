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
def isolate_product_master_database():
    app.dependency_overrides[company_setup_get_db] = override_get_db
    app.dependency_overrides[product_master_get_db] = override_get_db
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        app.dependency_overrides.pop(company_setup_get_db, None)
        app.dependency_overrides.pop(product_master_get_db, None)


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
            "chain_length": "1.6尺",
            "style_code": "NK-01",
        },
    )
    assert product.status_code == 201, product.text
    assert product.json()["chain_length"] == "1.6尺"
    assert product.json()["style_code"] == "NK-01"
    product_id = product.json()["id"]

    listed = client.get(f"/companies/{company_id}/products", params={"q": "22618"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["category_id"] == category_id

    updated = client.patch(
        f"/companies/{company_id}/products/{product_id}",
        json={"name": "黃金戒指（改款）", "labor_fee": "900", "chain_length": "1.8尺", "style_code": "NK-02"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "黃金戒指（改款）"
    assert updated.json()["labor_fee"] == "900.00"
    assert updated.json()["chain_length"] == "1.8尺"
    assert updated.json()["style_code"] == "NK-02"


def test_product_update_rejects_duplicate_code_suffix_and_barcode():
    company_id = setup_company()
    first = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-00001", "barcode": "471000000001", "name": "第一件戒指"},
    )
    second = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00E-00002", "barcode": "471000000002", "name": "第二件耳環"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    first_id = first.json()["id"]
    second_barcode = second.json()["barcode"]

    duplicate_suffix = client.patch(
        f"/companies/{company_id}/products/{first_id}",
        json={"product_code": "F00HF-00002"},
    )
    assert duplicate_suffix.status_code == 409

    duplicate_barcode = client.patch(
        f"/companies/{company_id}/products/{first_id}",
        json={"barcode": second_barcode},
    )
    assert duplicate_barcode.status_code == 409

    updated = client.patch(
        f"/companies/{company_id}/products/{first_id}",
        json={"product_code": "G00R-00003", "barcode": "471000000003"},
    )
    assert updated.status_code == 200
    assert updated.json()["product_code"] == "G00R-00003"
    assert updated.json()["barcode"] == "471000000003"


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


def test_product_label_lots_returns_empty_without_receipts_and_is_company_scoped():
    company_id = setup_company()
    product = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "LABEL-EMPTY-001", "barcode": "LABEL001", "name": "尚未收貨商品"},
    )
    assert product.status_code == 201, product.text

    empty_lots = client.get(
        f"/companies/{company_id}/products/{product.json()['id']}/label-lots"
    )
    assert empty_lots.status_code == 200
    assert empty_lots.json() == []

    other_company_id = client.post(
        "/companies", json={"code": "OTHER-LABEL", "name": "其他銀樓"}
    ).json()["id"]
    foreign_product = client.post(
        f"/companies/{other_company_id}/products",
        json={"product_code": "LABEL-FOREIGN-001", "barcode": "LABELFOREIGN", "name": "他公司商品"},
    )
    assert foreign_product.status_code == 201
    forbidden_lots = client.get(
        f"/companies/{company_id}/products/{foreign_product.json()['id']}/label-lots"
    )
    assert forbidden_lots.status_code == 404


def test_category_update_edit_reactivate_and_protect_active_products():
    company_id = setup_company()
    category = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "RING", "name": "戒指", "sort_order": 10},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]
    edited = client.patch(
        f"/companies/{company_id}/product-categories/{category_id}",
        json={"name": "黃金戒指", "sort_order": 20},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "黃金戒指"
    assert edited.json()["sort_order"] == 20
    product = client.post(
        f"/companies/{company_id}/products",
        json={"category_id": category_id, "product_code": "CAT-00001", "name": "測試戒指"},
    )
    assert product.status_code == 201, product.text
    blocked = client.patch(
        f"/companies/{company_id}/product-categories/{category_id}",
        json={"is_active": False},
    )
    assert blocked.status_code == 409
    product_off = client.patch(
        f"/companies/{company_id}/products/{product.json()['id']}",
        json={"is_active": False},
    )
    assert product_off.status_code == 200, product_off.text
    deactivated = client.patch(
        f"/companies/{company_id}/product-categories/{category_id}",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False
    default_list = client.get(f"/companies/{company_id}/product-categories")
    all_list = client.get(f"/companies/{company_id}/product-categories", params={"include_inactive": True})
    assert all(row["id"] != category_id for row in default_list.json())
    assert any(row["id"] == category_id for row in all_list.json())
    reactivated = client.patch(
        f"/companies/{company_id}/product-categories/{category_id}",
        json={"is_active": True},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True


def test_category_update_rejects_foreign_and_cyclic_parent():
    company_id = setup_company()
    root = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "ROOT", "name": "根分類"},
    ).json()
    child = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "CHILD", "name": "子分類", "parent_id": root["id"]},
    ).json()
    cycle = client.patch(
        f"/companies/{company_id}/product-categories/{root['id']}",
        json={"parent_id": child["id"]},
    )
    assert cycle.status_code == 422
    other_company = client.post("/companies", json={"code": "OTHER", "name": "另一家公司"}).json()["id"]
    foreign = client.post(
        f"/companies/{other_company}/product-categories",
        json={"code": "FOREIGN", "name": "外部分類"},
    ).json()["id"]
    rejected = client.patch(
        f"/companies/{company_id}/product-categories/{root['id']}",
        json={"parent_id": foreign},
    )
    assert rejected.status_code == 404


def test_category_deactivation_blocks_active_children_and_reactivation_can_change_parent():
    company_id = setup_company()
    old_parent = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "OLD", "name": "舊上層"},
    ).json()
    new_parent = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "NEW", "name": "新上層"},
    ).json()
    child = client.post(
        f"/companies/{company_id}/product-categories",
        json={"code": "CHILD", "name": "子分類", "parent_id": old_parent["id"]},
    ).json()

    blocked_parent = client.patch(
        f"/companies/{company_id}/product-categories/{old_parent['id']}",
        json={"is_active": False},
    )
    assert blocked_parent.status_code == 409

    child_off = client.patch(
        f"/companies/{company_id}/product-categories/{child['id']}",
        json={"is_active": False},
    )
    assert child_off.status_code == 200
    parent_off = client.patch(
        f"/companies/{company_id}/product-categories/{old_parent['id']}",
        json={"is_active": False},
    )
    assert parent_off.status_code == 200

    child_reactivated = client.patch(
        f"/companies/{company_id}/product-categories/{child['id']}",
        json={"is_active": True, "parent_id": new_parent["id"]},
    )
    assert child_reactivated.status_code == 200, child_reactivated.text
    assert child_reactivated.json()["parent_id"] == new_parent["id"]
    assert child_reactivated.json()["is_active"] is True
