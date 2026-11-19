from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.site import Site
from app.models.sale import Sale, SaleLine


def test_sales_and_lines_preserve_transaction_time_price_snapshots():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            company = Company(code="C1", name="測試公司")
            session.add(company)
            session.flush()
            site = Site(company_id=company.id, code="S1", name="一店")
            session.add(site)
            session.flush()
            sale = Sale(
                company_id=company.id, site_id=site.id, sale_no="S-20261119-0001",
                status="COMPLETED", payment_method="CARD", currency_code="TWD",
                subtotal=Decimal("10000"), card_fee=Decimal("500"),
                final_amount=Decimal("10500"),
                completed_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
            )
            session.add(sale)
            session.flush()
            line = SaleLine(
                sale_id=sale.id, line_no=1, product_name_snapshot="黃金戒指",
                product_code_snapshot="G00R-00001", barcode_snapshot="471000000001",
                gross_weight=Decimal("1.2500"), net_weight=Decimal("1.2000"),
                weight_unit_code="QIAN", labor_fee=Decimal("800"),
                sell_gold_price_value=Decimal("12000"), sell_gold_price_unit_code="TWD_PER_QIAN",
                buy_gold_price_value=Decimal("11000"), buy_gold_price_unit_code="TWD_PER_QIAN",
                price_currency_code="TWD",
                price_effective_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
                trade_in_source="EXTERNAL", old_gold_weight=Decimal("1.3333"),
                trade_in_ratio=Decimal("0.95"), adjusted_old_gold_weight=Decimal("1.26"),
                pricing_rule_version="legacy-v1", subtotal=Decimal("9680"),
                card_fee=Decimal("484"), final_amount=Decimal("10164"),
            )
            session.add(line)
            session.commit()
            loaded = session.get(SaleLine, line.id)
            assert loaded is not None
            assert loaded.sell_gold_price_value == Decimal("12000.0000")
            assert loaded.adjusted_old_gold_weight == Decimal("1.2600")
            assert loaded.pricing_rule_version == "legacy-v1"
            assert session.get(Sale, sale.id).final_amount == Decimal("10500.00")
    finally:
        engine.dispose()


def test_model_metadata_contains_sales_tables():
    assert "sales" in Base.metadata.tables
    assert "sale_lines" in Base.metadata.tables
    assert "sell_gold_price_id" in Base.metadata.tables["sale_lines"].c
