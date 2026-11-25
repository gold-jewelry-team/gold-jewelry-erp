import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.routers.company_setup import get_db

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
def isolate_company_setup_database():
    # Other test modules also use the global FastAPI app and may clear overrides.
    # Reinstall this module's override for every test to prevent CI-order coupling.
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        # Never restore another module's stale override: all tests share app.
        app.dependency_overrides.pop(get_db, None)


def teardown_module():
    engine.dispose()


def test_company_site_and_storage_location_setup_flow():
    company_response = client.post("/companies", json={"code": "MAIN", "name": "測試銀樓"})
    assert company_response.status_code == 201
    company = company_response.json()

    duplicate = client.post("/companies", json={"code": "MAIN", "name": "重複公司"})
    assert duplicate.status_code == 409

    site_response = client.post(
        f"/companies/{company['id']}/sites",
        json={"code": "SHOP01", "name": "總店"},
    )
    assert site_response.status_code == 201
    site = site_response.json()

    location_response = client.post(
        f"/companies/{company['id']}/sites/{site['id']}/storage-locations",
        json={"code": "SHOWCASE", "name": "展示櫃", "location_type": "STORE_FLOOR"},
    )
    assert location_response.status_code == 201
    assert location_response.json()["location_type"] == "STORE_FLOOR"

    listed = client.get(f"/companies/{company['id']}/sites/{site['id']}/storage-locations")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_storage_location_rejects_site_from_another_company():
    first = client.post("/companies", json={"code": "A", "name": "甲公司"}).json()
    second = client.post("/companies", json={"code": "B", "name": "乙公司"}).json()
    site = client.post(
        f"/companies/{second['id']}/sites",
        json={"code": "S1", "name": "乙公司據點"},
    ).json()

    response = client.post(
        f"/companies/{first['id']}/sites/{site['id']}/storage-locations",
        json={"code": "SAFE", "name": "保險櫃", "location_type": "SAFE"},
    )
    assert response.status_code == 404


def test_company_site_and_location_update_activation_safety():
    from uuid import UUID

    company = client.post("/companies", json={"code": "SAFE", "name": "安全測試公司"}).json()
    company_id = company["id"]
    site = client.post(
        f"/companies/{company_id}/sites",
        json={"code": "SHOP", "name": "總店"},
    ).json()
    site_id = site["id"]
    location = client.post(
        f"/companies/{company_id}/sites/{site_id}/storage-locations",
        json={"code": "SAFE01", "name": "保險櫃", "location_type": "SAFE"},
    ).json()
    location_id = location["id"]

    company_edit = client.patch(
        f"/companies/{company_id}",
        json={"name": "安全測試公司（已更名）", "tax_id": "12345678"},
    )
    assert company_edit.status_code == 200, company_edit.text
    assert company_edit.json()["name"] == "安全測試公司（已更名）"

    site_edit = client.patch(
        f"/companies/{company_id}/sites/{site_id}",
        json={"name": "總店（已更名）", "phone": "02-12345678"},
    )
    assert site_edit.status_code == 200, site_edit.text
    assert site_edit.json()["name"] == "總店（已更名）"

    location_edit = client.patch(
        f"/companies/{company_id}/sites/{site_id}/storage-locations/{location_id}",
        json={"name": "一號保險櫃", "description": "貴重商品存放處"},
    )
    assert location_edit.status_code == 200, location_edit.text
    assert location_edit.json()["name"] == "一號保險櫃"

    company_blocked = client.patch(
        f"/companies/{company_id}", json={"is_active": False}
    )
    assert company_blocked.status_code == 409
    site_blocked = client.patch(
        f"/companies/{company_id}/sites/{site_id}", json={"is_active": False}
    )
    assert site_blocked.status_code == 409

    with TestingSessionLocal() as db:
        product = Product(
            company_id=UUID(company_id),
            product_code="SAFE-ITEM-001",
            name="保險櫃庫存測試商品",
        )
        db.add(product)
        db.flush()
        db.add(InventoryMovement(
            company_id=UUID(company_id),
            site_id=UUID(site_id),
            product_id=product.id,
            movement_type="RECEIPT",
            to_location_id=UUID(location_id),
            quantity=1,
        ))
        db.commit()
        product_id = product.id

    stock_blocked = client.patch(
        f"/companies/{company_id}/sites/{site_id}/storage-locations/{location_id}",
        json={"is_active": False},
    )
    assert stock_blocked.status_code == 409

    with TestingSessionLocal() as db:
        db.add(InventoryMovement(
            company_id=UUID(company_id),
            site_id=UUID(site_id),
            product_id=product_id,
            movement_type="SALE",
            from_location_id=UUID(location_id),
            quantity=1,
        ))
        db.commit()

    location_off = client.patch(
        f"/companies/{company_id}/sites/{site_id}/storage-locations/{location_id}",
        json={"is_active": False},
    )
    assert location_off.status_code == 200, location_off.text
    site_off = client.patch(
        f"/companies/{company_id}/sites/{site_id}", json={"is_active": False}
    )
    assert site_off.status_code == 200, site_off.text
    company_off = client.patch(
        f"/companies/{company_id}", json={"is_active": False}
    )
    assert company_off.status_code == 200, company_off.text

    assert client.get("/companies").json() == []
    all_companies = client.get("/companies", params={"include_inactive": True}).json()
    assert any(row["id"] == company_id for row in all_companies)

    company_on = client.patch(f"/companies/{company_id}", json={"is_active": True})
    assert company_on.status_code == 200
    site_on = client.patch(
        f"/companies/{company_id}/sites/{site_id}", json={"is_active": True}
    )
    assert site_on.status_code == 200
    location_on = client.patch(
        f"/companies/{company_id}/sites/{site_id}/storage-locations/{location_id}",
        json={"is_active": True},
    )
    assert location_on.status_code == 200


def test_company_setup_updates_are_company_scoped_and_require_active_parents():
    first = client.post("/companies", json={"code": "FIRST", "name": "第一家公司"}).json()
    second = client.post("/companies", json={"code": "SECOND", "name": "第二家公司"}).json()
    foreign_site = client.post(
        f"/companies/{second['id']}/sites",
        json={"code": "FOREIGN", "name": "外部據點"},
    ).json()
    foreign_update = client.patch(
        f"/companies/{first['id']}/sites/{foreign_site['id']}",
        json={"name": "不應更新"},
    )
    assert foreign_update.status_code == 404

    deactivated = client.patch(f"/companies/{first['id']}", json={"is_active": False})
    assert deactivated.status_code == 200
    blocked_site = client.post(
        f"/companies/{first['id']}/sites",
        json={"code": "BLOCKED", "name": "不可建立"},
    )
    assert blocked_site.status_code == 422


