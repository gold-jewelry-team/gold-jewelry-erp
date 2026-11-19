"""Write and query gold price history without mutating existing price rows."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.gold_price import GoldPrice
from app.models.site import Site


def create_gold_price(
    session: Session,
    *,
    company_id: UUID,
    price_type: str,
    price_value: Decimal,
    unit_code: str,
    effective_at: datetime,
    site_id: UUID | None = None,
    currency_code: str = "TWD",
    source: str = "MANUAL",
    note: str | None = None,
) -> GoldPrice:
    """Append a price history row after validating its company/site scope.

    The caller owns the transaction and decides when to commit. Existing
    records are never updated by this service.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError("找不到指定公司。")
    if site_id is not None:
        site = session.get(Site, site_id)
        if site is None or site.company_id != company_id:
            raise ValueError("指定據點不存在或不屬於該公司。")
    if price_type not in ("BUY", "SELL"):
        raise ValueError("金價類型必須是 BUY 或 SELL。")
    if price_value <= 0:
        raise ValueError("金價必須大於 0。")
    if not unit_code or len(unit_code) > 20:
        raise ValueError("計價單位不可空白，且長度不可超過 20 字元。")
    if len(currency_code) != 3:
        raise ValueError("幣別必須使用三碼代碼，例如 TWD。")
    if source not in ("MANUAL", "IMPORT", "SYSTEM"):
        raise ValueError("不支援的金價來源。")

    price = GoldPrice(
        company_id=company_id,
        site_id=site_id,
        price_type=price_type,
        price_value=price_value,
        currency_code=currency_code.upper(),
        unit_code=unit_code,
        effective_at=effective_at,
        source=source,
        note=note,
    )
    session.add(price)
    session.flush()
    return price


def list_gold_prices(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID | None = None,
    price_type: str | None = None,
    limit: int = 100,
) -> list[GoldPrice]:
    """List a company's history, optionally narrowed to one site and type."""
    if not 1 <= limit <= 500:
        raise ValueError("查詢筆數必須介於 1 到 500。")
    statement = select(GoldPrice).where(GoldPrice.company_id == company_id)
    if site_id is not None:
        statement = statement.where(GoldPrice.site_id == site_id)
    if price_type is not None:
        if price_type not in ("BUY", "SELL"):
            raise ValueError("金價類型必須是 BUY 或 SELL。")
        statement = statement.where(GoldPrice.price_type == price_type)
    statement = statement.order_by(
        GoldPrice.effective_at.desc(), GoldPrice.created_at.desc()
    ).limit(limit)
    return list(session.scalars(statement).all())
