from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.product import Product
from app.models.site import Site
from app.models.supplier_payable import SupplierBill
from app.routers import product_master, purchases, suppliers


@pytest.fixture
def purchase_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        company = Company(code="PO-EDIT", name="採購草稿測試公司")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        product_a = Product(
            company_id=company.id, product_code="PO-A-001", name="測試商品A",
            gross_weight=Decimal("1.2"), net_weight=Decimal("1.1"),
        )
        product_b = Product(
            company_id=company.id, product_code="PO-B-001", name="測試商品B",
            gross_weight=Decimal("2.2"), net_weight=Decimal("2.0"),
        )
        db.add_all([site, product_a, product_b])
        db.commit()
        company_id, site_id, product_a_id, product_b_id = company.id, site.id, product_a.id, product_b.id

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[suppliers.get_db] = override
    app.dependency_overrides[purchases.get_db] = override
    app.dependency_overrides[product_master.get_db] = override
    try:
        client = TestClient(app)
        supplier = client.post(
            f"/companies/{company_id}/suppliers",
            json={"code": "SUP-EDIT", "name": "草稿測試供應商"},
        )
        assert supplier.status_code == 201, supplier.text
        yield client, company_id, site_id, supplier.json()["id"], product_a_id, product_b_id, Session
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _create_draft(client, company_id, site_id, supplier_id, product_id, purchase_no="PO-DRAFT-001"):
    response = client.post(
        f"/companies/{company_id}/purchases",
        json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_no": purchase_no,
            "order_date": date.today().isoformat(),
            "expected_date": None,
            "currency_code": "TWD",
            "note": "原始草稿",
            "lines": [{
                "product_id": str(product_id),
                "quantity": "1",
                "weight": "1.1000",
                "weight_unit_code": "QIAN",
                "unit_cost": "10000.00",
                "cost_labor_fee": "300.00",
                "note": "原始明細",
            }],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_purchase_draft_can_update_header_and_replace_lines(purchase_context):
    client, company_id, site_id, supplier_id, product_a, product_b, _Session = purchase_context
    draft = _create_draft(client, company_id, site_id, supplier_id, product_a)
    updated = client.patch(
        f"/companies/{company_id}/purchases/{draft['id']}",
        json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_no": "PO-DRAFT-UPDATED",
            "order_date": "2026-11-22",
            "expected_date": "2026-11-30",
            "currency_code": "USD",
            "note": "修改後草稿",
            "lines": [
                {
                    "product_id": str(product_b),
                    "quantity": "2",
                    "weight": "2.5000",
                    "weight_unit_code": "GRAM",
                    "unit_cost": "120.00",
                    "cost_labor_fee": "15.00",
                    "note": "新增商品B",
                }
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["purchase_no"] == "PO-DRAFT-UPDATED"
    assert updated.json()["currency_code"] == "USD"
    assert updated.json()["note"] == "修改後草稿"
    assert updated.json()["status"] == "DRAFT"
    assert len(updated.json()["lines"]) == 1
    assert updated.json()["lines"][0]["product_id"] == str(product_b)
    assert updated.json()["lines"][0]["quantity"] == "2.000"

    submitted = client.post(f"/companies/{company_id}/purchases/{draft['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    locked = client.patch(
        f"/companies/{company_id}/purchases/{draft['id']}",
        json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_no": "PO-LOCKED",
            "order_date": date.today().isoformat(),
            "currency_code": "TWD",
            "lines": [{
                "product_id": str(product_b),
                "quantity": "1",
                "unit_cost": "1",
            }],
        },
    )
    assert locked.status_code == 422


def test_purchase_draft_cannot_change_when_valid_supplier_bill_is_linked(purchase_context):
    client, company_id, site_id, supplier_id, product_a, _product_b, Session = purchase_context
    draft = _create_draft(client, company_id, site_id, supplier_id, product_a, "PO-BILLED-001")
    with Session() as db:
        db.add(SupplierBill(
            company_id=company_id,
            site_id=site_id,
            supplier_id=__import__("uuid").UUID(supplier_id),
            purchase_id=__import__("uuid").UUID(draft["id"]),
            bill_no="BILL-LINKED-001",
            bill_date=date.today(),
            total_amount=Decimal("1000.00"),
        ))
        db.commit()

    blocked = client.patch(
        f"/companies/{company_id}/purchases/{draft['id']}",
        json={
            "site_id": str(site_id),
            "supplier_id": str(supplier_id),
            "purchase_no": "PO-BILLED-CHANGED",
            "order_date": date.today().isoformat(),
            "currency_code": "TWD",
            "lines": [{
                "product_id": str(product_a),
                "quantity": "1",
                "unit_cost": "100",
            }],
        },
    )
    assert blocked.status_code == 422
