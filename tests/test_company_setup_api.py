from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.routers.company_setup import get_db

engine = create_engine("sqlite+pysqlite:///:memory:")
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def teardown_module():
    app.dependency_overrides.clear()
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
