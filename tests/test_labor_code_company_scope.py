from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.routers.labor_code_settings import get_db


def test_labor_code_config_is_isolated_per_company():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    first = Company(code="DARK-A", name="甲銀樓")
    second = Company(code="DARK-B", name="乙銀樓")
    session.add_all([first, second])
    session.commit()
    first_id, second_id = first.id, second.id
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
        saved = client.put(
            f"/companies/{first_id}/labor-code-config",
            json={"prefix": "ZX", "mappings": [{"digit": 0, "code_char": "Q"}]},
        )
        assert saved.status_code == 200, saved.text

        first_config = client.get(f"/companies/{first_id}/labor-code-config")
        second_config = client.get(f"/companies/{second_id}/labor-code-config")
        assert first_config.status_code == 200
        assert second_config.status_code == 200
        assert first_config.json()["prefix"] == "ZX"
        assert first_config.json()["mappings"] == [{"digit": 0, "code_char": "Q"}]
        assert second_config.json()["prefix"] == "A"
        assert second_config.json()["mappings"] == []

        cleared = client.put(
            f"/companies/{first_id}/labor-code-config",
            json={"prefix": "ZX", "mappings": []},
        )
        assert cleared.status_code == 200
        assert cleared.json()["mappings"] == []
        assert client.get(f"/companies/{second_id}/labor-code-config").json()["mappings"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
