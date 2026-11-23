from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.sale import Sale
from app.models.site import Site
from app.routers import sales


def test_sale_endpoints_do_not_expose_or_mutate_another_company_sale():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    owner = Company(code="SALE-OWNER", name="銷售單所屬公司")
    other = Company(code="SALE-OTHER", name="其他公司")
    db.add_all([owner, other])
    db.flush()
    site = Site(company_id=owner.id, code="MAIN", name="總店")
    db.add(site)
    db.flush()
    sale = Sale(
        company_id=owner.id,
        site_id=site.id,
        sale_no="SO-COMPANY-ISOLATION-001",
        status="DRAFT",
        payment_method="CASH",
        currency_code="TWD",
        subtotal=Decimal("0.00"),
        card_amount=Decimal("0.00"),
        card_fee=Decimal("0.00"),
        final_amount=Decimal("0.00"),
    )
    db.add(sale)
    db.commit()
    owner_id, other_id, sale_id = owner.id, other.id, sale.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[sales.get_db] = override_db
    try:
        client = TestClient(app)
        listing = client.get(f"/companies/{other_id}/sales")
        assert listing.status_code == 200, listing.text
        assert listing.json() == []

        detail = client.get(f"/companies/{other_id}/sales/{sale_id}")
        assert detail.status_code == 404

        complete = client.post(
            f"/companies/{other_id}/sales/{sale_id}/complete"
        )
        assert complete.status_code == 422

        void = client.post(f"/companies/{other_id}/sales/{sale_id}/void")
        assert void.status_code == 422

        verify = TestSession()
        persisted = verify.scalar(select(Sale).where(Sale.id == sale_id))
        assert persisted.company_id == owner_id
        assert persisted.status == "DRAFT"
        verify.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
