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


def test_gold_material_fine_weight_and_valuation_use_half_up_precision():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    company = Company(code="GM-ROUNDING", name="金料精度四捨五入測試")
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
        created = client.post(
            f"/companies/{company_id}/gold-material/movements",
            json={
                "site_id": str(site_id),
                "movement_no": "GM-ROUND-HALF-UP",
                "movement_type": "OPENING",
                "purity_label": "9999",
                "purity_ratio": "0.999900",
                "gross_weight": "1.2345",
                "loss_weight": "0.0345",
                "weight_unit_code": "QIAN",
                "gold_price_value": "12000.00",
                "gold_price_unit_code": "QIAN",
                "deduction_amount": "0.00",
            },
        )
        assert created.status_code == 201, created.text
        result = created.json()
        assert result["net_weight"] == "1.2000"
        # 1.2000 QIAN × 3.75 g × 0.9999 = 4.49955 g,
        # rounded half-up to four decimal places.
        assert result["fine_gold_weight_g"] == "4.4996"
        # 4.4996 g / 3.75 g per QIAN × NT$12,000 = NT$14,398.72.
        assert result["valuation_amount"] == "14398.72"

        balance = client.get(
            f"/companies/{company_id}/gold-material/balance",
            params={"site_id": str(site_id)},
        )
        assert balance.status_code == 200, balance.text
        assert Decimal(balance.json()["fine_gold_weight_g"]) == Decimal("4.4996")

        verify = TestSession()
        movement = verify.query(GoldMaterialMovement).one()
        assert movement.net_weight == Decimal("1.2000")
        assert movement.fine_gold_weight_g == Decimal("4.4996")
        assert movement.valuation_amount == Decimal("14398.72")
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
