"""Sales draft pricing and inventory completion services."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.sale import Sale, SaleLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.services.inventory import create_inventory_movement
from app.services.daily_closing import assert_business_day_open
from app.services.pricing.gold_prices import get_effective_gold_price
from app.services.pricing.sales import SalePricingInput, calculate_sale_amount

PRICING_RULE_VERSION = "legacy-v1"


def create_sale_draft(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    sale_no: str,
    payment_method: str,
    lines: list[dict],
    note: str | None = None,
    at: datetime | None = None,
) -> Sale:
    """Create a draft sale with immutable price and product snapshots."""
    if payment_method not in {"CASH", "CARD", "TRANSFER", "OTHER"}:
        raise ValueError("不支援的付款方式。")
    site = session.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    if not lines:
        raise ValueError("銷售明細不可空白。")

    priced_at = at or datetime.now(timezone.utc)
    sale = Sale(
        company_id=company_id,
        site_id=site_id,
        sale_no=sale_no,
        payment_method=payment_method,
        currency_code="TWD",
        subtotal=Decimal("0"),
        card_fee=Decimal("0"),
        final_amount=Decimal("0"),
        note=note,
    )
    session.add(sale)
    session.flush()

    subtotal_total = Decimal("0")
    card_fee_total = Decimal("0")
    final_total = Decimal("0")

    for line_no, item in enumerate(lines, start=1):
        product = session.execute(
            select(Product).where(
                Product.id == item["product_id"],
                Product.company_id == company_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if product is None or not product.is_active:
            raise ValueError("商品不存在、不屬於指定公司或已停用。")

        location = session.get(StorageLocation, item["source_location_id"])
        if location is None or location.site_id != site_id or not location.is_active:
            raise ValueError("出貨儲存位置不存在、未啟用或不屬於銷售據點。")

        sell_price = get_effective_gold_price(
            session, company_id=company_id, site_id=site_id, price_type="SELL", at=priced_at
        )
        buy_price = get_effective_gold_price(
            session, company_id=company_id, site_id=site_id, price_type="BUY", at=priced_at
        )
        if sell_price is None or buy_price is None:
            raise ValueError("找不到交易時間有效的買入或賣出金價，請先建立金價。")
        if sell_price.unit_code != product.weight_unit_code or buy_price.unit_code != product.weight_unit_code:
            raise ValueError("商品重量單位必須與買入、賣出金價單位一致，請先統一單位設定。")
        if sell_price.currency_code != "TWD" or buy_price.currency_code != "TWD":
            raise ValueError("目前銷售計價僅支援 TWD 金價。")

        old_weight = item.get("old_gold_weight", Decimal("0"))
        has_trade_in = old_weight > 0
        trade_in_source = item.get("trade_in_source") if has_trade_in else None
        ratio = item.get("trade_in_ratio", Decimal("0.95"))
        labor = item.get("labor_fee")
        if labor is None:
            labor = product.labor_fee

        result = calculate_sale_amount(SalePricingInput(
            new_weight=product.net_weight,
            sell_gold_price=sell_price.price_value,
            buy_gold_price=buy_price.price_value,
            labor_fee=labor,
            has_trade_in=has_trade_in,
            trade_in_source=trade_in_source,
            old_weight=old_weight,
            trade_in_ratio=ratio,
            is_credit_card=payment_method == "CARD",
        ))

        line = SaleLine(
            sale_id=sale.id,
            line_no=line_no,
            product_id=product.id,
            source_location_id=location.id,
            product_code_snapshot=product.product_code,
            barcode_snapshot=product.barcode,
            product_name_snapshot=product.name,
            gross_weight=product.gross_weight,
            net_weight=product.net_weight,
            weight_unit_code=product.weight_unit_code,
            labor_fee=labor,
            sell_gold_price_id=sell_price.id,
            sell_gold_price_value=sell_price.price_value,
            sell_gold_price_unit_code=sell_price.unit_code,
            buy_gold_price_id=buy_price.id,
            buy_gold_price_value=buy_price.price_value,
            buy_gold_price_unit_code=buy_price.unit_code,
            price_currency_code="TWD",
            price_effective_at=max(sell_price.effective_at, buy_price.effective_at),
            trade_in_source=trade_in_source,
            old_gold_weight=old_weight if has_trade_in else Decimal("0"),
            trade_in_ratio=(Decimal("1") if trade_in_source == "LOCAL" else ratio) if has_trade_in else None,
            adjusted_old_gold_weight=result.adjusted_old_weight,
            pricing_rule_version=PRICING_RULE_VERSION,
            subtotal=result.subtotal,
            card_fee=result.card_fee,
            final_amount=result.final_amount,
        )
        session.add(line)
        subtotal_total += result.subtotal
        card_fee_total += result.card_fee
        final_total += result.final_amount

    sale.subtotal = subtotal_total
    sale.card_fee = card_fee_total
    sale.final_amount = final_total
    session.flush()
    return sale


def complete_sale(session: Session, *, company_id: UUID, sale_id: UUID) -> Sale:
    """Atomically deduct each sold item and complete the sale."""
    sale = session.execute(
        select(Sale).where(Sale.id == sale_id, Sale.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    if sale.status != "DRAFT":
        raise ValueError("只有草稿銷售單可以完成。")
    lines = list(session.scalars(
        select(SaleLine).where(SaleLine.sale_id == sale.id).order_by(SaleLine.line_no)
    ).all())
    if not lines:
        raise ValueError("銷售單沒有商品明細。")

    completed_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=sale.site_id, at=completed_at)
    for line in lines:
        if line.product_id is None or line.source_location_id is None:
            raise ValueError("銷售明細缺少商品或出貨儲存位置。")
        create_inventory_movement(
            session,
            company_id=company_id,
            site_id=sale.site_id,
            product_id=line.product_id,
            movement_type="SALE",
            quantity=Decimal("1"),
            from_location_id=line.source_location_id,
            weight=line.net_weight,
            weight_unit_code=line.weight_unit_code,
            occurred_at=completed_at,
            reference_type="SALE_LINE",
            reference_id=line.id,
            note=f"銷售單 {sale.sale_no}",
        )
    sale.status = "COMPLETED"
    sale.completed_at = completed_at
    session.flush()
    return sale


def void_sale_draft(session: Session, *, company_id: UUID, sale_id: UUID) -> Sale:
    sale = session.execute(
        select(Sale).where(Sale.id == sale_id, Sale.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    if sale.status != "DRAFT":
        raise ValueError("只有草稿銷售單可以作廢；已完成銷售請走退貨流程。")
    sale.status = "VOID"
    sale.voided_at = datetime.now(timezone.utc)
    session.flush()
    return sale
