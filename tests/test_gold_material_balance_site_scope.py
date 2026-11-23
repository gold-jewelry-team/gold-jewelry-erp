from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.site import Site
from app.routers import gold_material


def test_gold_material_balance_rejects_site_from_another_company():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="GMBAL-OWNER", name="金料餘額所屬公司")
    other = Company(code="GMBAL-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    owner_site = Site(company_id=owner.id, code="MAIN", name="總店")
    other_site = Site(company_id=other.id, code="MAIN", name="其他公司總店")
    db.add_all([owner_site, other_site])
    db.commit()
    owner_id, owner_site_id, other_site_id = owner.id, owner_site.id, other_site.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[gold_material.get_db] = override_db
    try:
        client = TestClient(app)
        base = f"/companies/{owner_id}/gold-material/balance"
        valid = client.get(base, params={"site_id": str(owner_site_id)})
        assert valid.status_code == 200, valid.text
        assert Decimal(valid.json()["fine_gold_weight_g"]) == Decimal("0")

        foreign = client.get(base, params={"site_id": str(other_site_id)})
        assert foreign.status_code == 404
        assert "找不到指定公司據點" in foreign.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
