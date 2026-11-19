"""Supplier purchase-cost calculations ported from the legacy application."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.services.pricing.rounding import as_decimal, round_twd_like_legacy

PurchaseMode = Literal["WEIGHT_EXCHANGE", "CASH_BUY"]


@dataclass(frozen=True)
class PurchaseCostInput:
    mode: PurchaseMode
    in_weight: Decimal
    out_weight: Decimal
    gold_price: Decimal
    labor_fee: Decimal = Decimal("0")


def calculate_purchase_cost(payload: PurchaseCostInput) -> Decimal:
    """Return the legacy purchase total rounded to a whole TWD dollar."""
    in_weight = as_decimal(payload.in_weight)
    out_weight = as_decimal(payload.out_weight)
    gold_price = as_decimal(payload.gold_price)
    labor = as_decimal(payload.labor_fee)

    if in_weight < 0 or out_weight < 0 or labor < 0:
        raise ValueError("進貨重量、付出重量及工錢不可小於 0。")
    if gold_price <= 0:
        raise ValueError("金價必須大於 0。")
    if payload.mode == "WEIGHT_EXCHANGE":
        raw_total = (in_weight - out_weight) * gold_price + labor
    elif payload.mode == "CASH_BUY":
        raw_total = in_weight * gold_price + labor
    else:
        raise ValueError("不支援的進貨計價方式。")
    return round_twd_like_legacy(raw_total)
