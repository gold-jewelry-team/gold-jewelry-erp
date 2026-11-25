from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.product import Product
from app.routers import inventory, product_master, purchases, suppliers


def test_two_gold_products_purchase_receive_stock_and_barcode_flow():
    """Exercise the complete supplier -> purchase -> receipt -> stock -> label API flow."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()

    company = Company(code="E2E-STORE", name="兩種黃金商品流程測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    session.add(site)
    session.flush()
    safe = StorageLocation(
        site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE"
    )
    display = StorageLocation(
        site_id=site.id, code="SHOW", name="展示櫃", location_type="STORE_FLOOR"
    )
    ring = Product(
        company_id=company.id,
        product_code="G00R-99001",
        barcode="471009900001",
        name="測試黃金戒指",
        gross_weight=Decimal("1.25"),
        net_weight=Decimal("1.20"),
    )
    bracelet = Product(
        company_id=company.id,
        product_code="G00HF-99002",
        barcode="471009900002",
        name="測試黃金手環",
        gross_weight=Decimal("2.60"),
        net_weight=Decimal("2.50"),
    )
    session.add_all([safe, display, ring, bracelet])
    session.commit()

    company_id = company.id
    site_id = site.id
    safe_id = safe.id
    display_id = display.id
    ring_id = ring.id
    bracelet_id = bracelet.id
    session.close()

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    overrides = {
        suppliers.get_db: override_db,
        purchases.get_db: override_db,
        product_master.get_db: override_db,
        inventory.get_db: override_db,
    }
    app.dependency_overrides.update(overrides)
    try:
        client = TestClient(app)

        supplier_response = client.post(
            f"/companies/{company_id}/suppliers",
            json={"code": "SUP-E2E", "name": "測試黃金供應商"},
        )
        assert supplier_response.status_code == 201, supplier_response.text
        supplier_id = supplier_response.json()["id"]

        purchase_response = client.post(
            f"/companies/{company_id}/purchases",
            json={
                "site_id": str(site_id),
                "supplier_id": supplier_id,
                "purchase_no": "PO-E2E-GOLD-001",
                "order_date": date.today().isoformat(),
                "currency_code": "TWD",
                "lines": [
                    {
                        "product_id": str(ring_id),
                        "quantity": "1",
                        "weight": "1.20",
                        "weight_unit_code": "QIAN",
                        "unit_cost": "12000",
                        "cost_labor_fee": "350",
                    },
                    {
                        "product_id": str(bracelet_id),
                        "quantity": "1",
                        "weight": "2.50",
                        "weight_unit_code": "QIAN",
                        "unit_cost": "12000",
                        "cost_labor_fee": "500",
                    },
                ],
            },
        )
        assert purchase_response.status_code == 201, purchase_response.text
        purchase = purchase_response.json()
        assert purchase["status"] == "DRAFT"
        assert len(purchase["lines"]) == 2
        line_by_product = {
            line["product_id"]: line for line in purchase["lines"]
        }

        submitted = client.post(
            f"/companies/{company_id}/purchases/{purchase['id']}/submit"
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "ORDERED"

        ring_receipt = client.post(
            f"/companies/{company_id}/purchases/{purchase['id']}/receive",
            json={
                "purchase_line_id": line_by_product[str(ring_id)]["id"],
                "location_id": str(safe_id),
                "received_quantity": "1",
                "idempotency_key": str(uuid4()),
            },
        )
        assert ring_receipt.status_code == 200, ring_receipt.text
        assert ring_receipt.json()["status"] == "PARTIALLY_RECEIVED"

        bracelet_receipt = client.post(
            f"/companies/{company_id}/purchases/{purchase['id']}/receive",
            json={
                "purchase_line_id": line_by_product[str(bracelet_id)]["id"],
                "location_id": str(display_id),
                "received_quantity": "1",
                "idempotency_key": str(uuid4()),
            },
        )
        assert bracelet_receipt.status_code == 200, bracelet_receipt.text
        assert bracelet_receipt.json()["status"] == "RECEIVED"

        stock_response = client.get(
            f"/companies/{company_id}/inventory/stock",
            params={"site_id": str(site_id)},
        )
        assert stock_response.status_code == 200, stock_response.text
        stock = {row["product_id"]: row for row in stock_response.json()}
        assert stock[str(ring_id)]["quantity"] == "1.000"
        assert stock[str(ring_id)]["location_code"] == "SAFE"
        assert stock[str(bracelet_id)]["quantity"] == "1.000"
        assert stock[str(bracelet_id)]["location_code"] == "SHOW"

        movements_response = client.get(
            f"/companies/{company_id}/inventory/movements",
            params={"movement_type": "RECEIPT"},
        )
        assert movements_response.status_code == 200, movements_response.text
        receipts = movements_response.json()
        assert len(receipts) == 2
        assert {row["product_id"] for row in receipts} == {
            str(ring_id), str(bracelet_id)
        }

        for product_id, expected_barcode, expected_supplier, expected_location in [
            (ring_id, "471009900001", "測試黃金供應商", "SAFE"),
            (bracelet_id, "471009900002", "測試黃金供應商", "SHOW"),
        ]:
            lookup = client.get(
                f"/companies/{company_id}/products/lookup",
                params={"code": expected_barcode},
            )
            assert lookup.status_code == 200, lookup.text
            assert lookup.json()["id"] == str(product_id)

            barcode_svg = client.get(
                f"/companies/{company_id}/products/{product_id}/barcode.svg"
            )
            assert barcode_svg.status_code == 200, barcode_svg.text
            assert "image/svg+xml" in barcode_svg.headers["content-type"]
            assert "<svg" in barcode_svg.text

            qr_svg = client.get(
                f"/companies/{company_id}/products/{product_id}/qr.svg"
            )
            assert qr_svg.status_code == 200, qr_svg.text
            assert "image/svg+xml" in qr_svg.headers["content-type"]
            assert "<svg" in qr_svg.text

            label_lots = client.get(
                f"/companies/{company_id}/products/{product_id}/label-lots"
            )
            assert label_lots.status_code == 200, label_lots.text
            lots = label_lots.json()
            assert len(lots) == 1
            assert lots[0]["purchase_no"] == "PO-E2E-GOLD-001"
            assert lots[0]["supplier_name"] == expected_supplier
            assert lots[0]["location_code"] == expected_location
            assert lots[0]["received_quantity"] == "1.000"
            assert lots[0]["currency_code"] == "TWD"
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)
        engine.dispose()
