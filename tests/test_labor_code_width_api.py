from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.routers.labor_code_settings import get_db


def test_labor_code_config_rejects_oversized_mapping_token():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    company = Company(code="DARK-LIMIT", name="暗碼長度測試")
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
        response = TestClient(app).put(
            f"/companies/{company_id}/labor-code-config",
            json={"prefix": "A", "mappings": [{"digit": 0, "code_char": "ABCDE"}]},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
