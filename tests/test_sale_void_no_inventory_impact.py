from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.services.inventory import create_inventory_movement, get_stock_balance
from app.services.sales import complete_sale, create_sale_draft, void_sale_draft


def test_voiding_draft_sale_does_not_deduct_stock_and_blocks_completion():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        company = Company(code="VOID-SALE", name="銷售作廢庫存測試")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        session.add(site)
        session.flush()
        location = StorageLocation(site_id=site.id, code="SAFE", name="保險櫃", location_type="SAFE")
        product = Product(
            company_id=company.id, product_code="VOID-SALE-001", name="作廢銷售測試商品",
            gross_weight=Decimal("1.2000"), net_weight=Decimal("1.0000"),
            weight_unit_code="QIAN", labor_fee=Decimal("300"),
        )
        session.add_all([location, product])
        session.flush()
        effective_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.add_all([
            GoldPrice(company_id=company.id, site_id=None, price_type="SELL",
                      price_value=Decimal("12000"), currency_code="TWD",
                      unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
            GoldPrice(company_id=company.id, site_id=None, price_type="BUY",
                      price_value=Decimal("11000"), currency_code="TWD",
                      unit_code="QIAN", effective_at=effective_at, source="MANUAL"),
        ])
        create_inventory_movement(
            session, company_id=company.id, site_id=site.id, product_id=product.id,
            movement_type="RECEIPT", quantity=Decimal("1"), to_location_id=location.id,
            weight=Decimal("1.0000"), weight_unit_code="QIAN",
        )
        sale = create_sale_draft(
            session, company_id=company.id, site_id=site.id, sale_no="SO-VOID-001",
            payment_method="CASH",
            lines=[{"product_id": product.id, "source_location_id": location.id}],
        )
        session.commit()
        assert sale.status == "DRAFT"
        assert get_stock_balance(session, product_id=product.id, location_id=location.id) == Decimal("1")

        voided = void_sale_draft(session, company_id=company.id, sale_id=sale.id)
        session.commit()
        assert voided.status == "VOID"
        assert voided.voided_at is not None
        assert get_stock_balance(session, product_id=product.id, location_id=location.id) == Decimal("1")
        assert session.query(InventoryMovement).filter_by(reference_type="SALE_LINE").count() == 0

        with pytest.raises(ValueError, match="只有草稿"):
            complete_sale(session, company_id=company.id, sale_id=sale.id)
        session.rollback()
        assert session.get(Sale, sale.id).status == "VOID"
        assert session.query(InventoryMovement).filter_by(reference_type="SALE_LINE").count() == 0
        assert get_stock_balance(session, product_id=product.id, location_id=location.id) == Decimal("1")
    finally:
        session.close()
        engine.dispose()
