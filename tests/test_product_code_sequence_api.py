import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.routers.company_setup import get_db as company_setup_get_db
from app.routers.product_code_sequence import get_db as sequence_get_db
from app.routers.product_master import get_db as product_master_get_db

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
    dependencies = [company_setup_get_db, sequence_get_db, product_master_get_db]
    for dep in dependencies:
        app.dependency_overrides[dep] = override_get_db
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        # Do not restore stale overrides installed by other test modules.
        for dep in dependencies:
            app.dependency_overrides.pop(dep, None)


def create_company():
    response = client.post("/companies", json={"code": "SEQ", "name": "流水號測試銀樓"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_company_sequence_generates_shared_number_across_prefixes():
    company_id = create_company()
    first = client.post(
        f"/companies/{company_id}/product-code-sequence/next",
        json={"prefix": "G00R-"},
    )
    second = client.post(
        f"/companies/{company_id}/product-code-sequence/next",
        json={"prefix": "F00HF-"},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["product_code"] == "G00R-00001"
    assert second.json()["product_code"] == "F00HF-00002"
    assert second.json()["next_number"] == 3


def test_manual_product_code_advances_shared_sequence():
    company_id = create_company()
    product = client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00E-22618", "name": "手動編號商品"},
    )
    assert product.status_code == 201, product.text
    generated = client.post(
        f"/companies/{company_id}/product-code-sequence/next",
        json={"prefix": "G00R-"},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["product_code"] == "G00R-22619"


def test_sequence_cannot_be_reset_below_existing_numeric_suffix():
    company_id = create_company()
    client.post(
        f"/companies/{company_id}/products",
        json={"product_code": "G00R-01000", "name": "既有商品"},
    )
    response = client.patch(
        f"/companies/{company_id}/product-code-sequence",
        json={"next_number": 1000},
    )
    assert response.status_code == 422
