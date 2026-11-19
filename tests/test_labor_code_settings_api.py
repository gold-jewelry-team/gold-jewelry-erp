from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.routers.labor_code_settings import get_db


def test_company_labor_code_config_defaults_and_round_trips():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="DARK", name="暗碼測試銀樓")
    session.add(company)
    session.commit()
    company_id = company.id
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        default = client.get(f"/companies/{company_id}/labor-code-config")
        assert default.status_code == 200
        assert default.json()["prefix"] == "A"
        assert default.json()["mappings"] == []

        mappings = [{"digit": digit, "code_char": f"X{digit}"} for digit in range(10)]
        saved = client.put(
            f"/companies/{company_id}/labor-code-config",
            json={"prefix": "ab12", "mappings": mappings},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["prefix"] == "AB12"
        assert len(saved.json()["mappings"]) == 10
        assert saved.json()["mappings"][0] == {"digit": 0, "code_char": "X0"}

        duplicate = client.put(
            f"/companies/{company_id}/labor-code-config",
            json={"prefix": "A", "mappings": [
                {"digit": 1, "code_char": "ONE"},
                {"digit": 1, "code_char": "DUP"},
            ]},
        )
        assert duplicate.status_code == 422

        reloaded = client.get(f"/companies/{company_id}/labor-code-config")
        assert reloaded.json()["prefix"] == "AB12"
        assert len(reloaded.json()["mappings"]) == 10
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
