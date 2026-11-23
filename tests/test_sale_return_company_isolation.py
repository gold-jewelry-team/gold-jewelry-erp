from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.site import Site
from app.routers import sales_returns


def test_sale_return_list_and_detail_are_scoped_to_company_and_parent_sale():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="RETURN-OWNER", name="退貨所屬公司")
    other = Company(code="RETURN-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    site = Site(company_id=owner.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    sale = Sale(
        company_id=owner.id,
        site_id=site.id,
        sale_no="SO-RETURN-ISOLATION-001",
        status="COMPLETED",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("1000.00"),
        card_amount=Decimal("0.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("1000.00"),
    )
    db.add(sale)
    db.flush()
    returned = SaleReturn(
        company_id=owner.id,
        site_id=site.id,
        sale_id=sale.id,
        return_no="RT-RETURN-ISOLATION-001",
        settlement_reversal_amount=Decimal("-1000.00"),
        currency_code="TWD",
        reason="測試退貨",
    )
    db.add(returned)
    db.commit()
    other_id, sale_id, return_id = other.id, sale.id, returned.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales_returns.get_db] = override_db
    try:
        client = TestClient(app)
        listing = client.get(
            f"/companies/{other_id}/sales/{sale_id}/returns"
        )
        assert listing.status_code == 200, listing.text
        assert listing.json() == []

        detail = client.get(
            f"/companies/{other_id}/sales/{sale_id}/returns/{return_id}"
        )
        assert detail.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
