from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.gold_material import GoldMaterialMovement
from app.models.site import Site
from app.routers import gold_material


def test_duplicate_gold_material_movement_number_returns_original_atomically():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="GOLD-MOVE-DUP", name="金料單號重複測試")
    db.add(company)
    db.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    db.add(site)
    db.commit()
    company_id, site_id = company.id, site.id
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
        base = f"/companies/{company_id}/gold-material/movements"
        payload = {
            "site_id": str(site_id),
            "movement_no": "GM-DUP-001",
            "movement_type": "OPENING",
            "source_type": "OPENING_BALANCE",
            "purity_label": "9999",
            "purity_ratio": "0.999900",
            "gross_weight": "10.0000",
            "loss_weight": "0.0000",
            "weight_unit_code": "G",
            "gold_price_value": "3000.00",
            "gold_price_unit_code": "G",
            "deduction_amount": "0.00",
        }
        first = client.post(base, json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["fine_gold_weight_g"] == "9.9990"

        duplicate = client.post(base, json=payload)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == first.json()["id"]

        balance = client.get(
            f"/companies/{company_id}/gold-material/balance",
            params={"site_id": str(site_id)},
        )
        assert balance.status_code == 200, balance.text
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("9.9990")

        verify = TestSession()
        rows = verify.query(GoldMaterialMovement).all()
        assert len(rows) == 1
        assert rows[0].movement_no == "GM-DUP-001"
        assert rows[0].gross_weight == Decimal("10.0000")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
