"""Effective gold-price lookup with site-specific override and company fallback."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.gold_price import GoldPrice

GoldPriceType = Literal["BUY", "SELL"]


def get_effective_gold_price(
    session: Session,
    *,
    company_id: UUID,
    price_type: GoldPriceType,
    at: datetime,
    site_id: UUID | None = None,
) -> GoldPrice | None:
    """Return the latest effective price; a site price takes precedence.

    A company-wide row (site_id NULL) is the fallback when no site-specific
    price is effective at the requested time. Future-dated rows are ignored.
    """
    if price_type not in ("BUY", "SELL"):
        raise ValueError("金價類型必須是 BUY 或 SELL。")

    if site_id is not None:
        site_statement = (
            select(GoldPrice)
            .where(
                GoldPrice.company_id == company_id,
                GoldPrice.site_id == site_id,
                GoldPrice.price_type == price_type,
                GoldPrice.effective_at <= at,
            )
            .order_by(GoldPrice.effective_at.desc(), GoldPrice.created_at.desc())
            .limit(1)
        )
        site_price = session.scalar(site_statement)
        if site_price is not None:
            return site_price

    company_statement = (
        select(GoldPrice)
        .where(
            GoldPrice.company_id == company_id,
            GoldPrice.site_id.is_(None),
            GoldPrice.price_type == price_type,
            GoldPrice.effective_at <= at,
        )
        .order_by(GoldPrice.effective_at.desc(), GoldPrice.created_at.desc())
        .limit(1)
    )
    return session.scalar(company_statement)
