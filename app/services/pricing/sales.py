"""Sales and old-gold trade-in pricing, ported from gold-inventory-system."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.services.pricing.rounding import as_decimal, round_twd_like_legacy, truncate_weight

TradeInSource = Literal["LOCAL", "EXTERNAL"]


@dataclass(frozen=True)
class SalePricingInput:
    new_weight: Decimal
    sell_gold_price: Decimal
    buy_gold_price: Decimal
    labor_fee: Decimal = Decimal("0")
    has_trade_in: bool = False
    trade_in_source: TradeInSource | None = None
    old_weight: Decimal = Decimal("0")
    trade_in_ratio: Decimal = Decimal("0.95")
    is_credit_card: bool = False


@dataclass(frozen=True)
class SalePricingResult:
    adjusted_old_weight: Decimal
    weight_difference: Decimal
    subtotal: Decimal
    card_fee: Decimal
    final_amount: Decimal
    settlement_direction: Literal["CUSTOMER_PAYS", "STORE_REFUNDS", "ZERO"]


def calculate_sale_amount(payload: SalePricingInput) -> SalePricingResult:
    """Calculate a sale using the legacy store/external trade-in rules.

    LOCAL old gold is credited at 100%. EXTERNAL old gold uses the supplied
    ratio (legacy UI default: 95%). Adjusted weight is truncated to 0.01.
    Card fee is 5% only when the pre-fee amount is positive.
    """
    new_weight = as_decimal(payload.new_weight)
    sell_rate = as_decimal(payload.sell_gold_price)
    buy_rate = as_decimal(payload.buy_gold_price)
    labor = as_decimal(payload.labor_fee)
    old_weight = as_decimal(payload.old_weight)
    ratio = as_decimal(payload.trade_in_ratio)

    if new_weight < 0 or old_weight < 0 or labor < 0:
        raise ValueError("重量與工錢不可小於 0。")
    if sell_rate <= 0 or buy_rate <= 0:
        raise ValueError("買入及賣出金價必須大於 0。")

    adjusted_old = Decimal("0")
    difference = new_weight
    subtotal = new_weight * sell_rate + labor

    if payload.has_trade_in:
        if old_weight <= 0:
            raise ValueError("舊金貼換必須輸入大於 0 的舊金重量。")
        if payload.trade_in_source not in ("LOCAL", "EXTERNAL"):
            raise ValueError("請選擇本店或外店舊金來源。")
        if payload.trade_in_source == "LOCAL":
            effective_ratio = Decimal("1")
        else:
            if ratio <= 0 or ratio > 1:
                raise ValueError("外店舊金折算比例必須大於 0 且不得超過 1。")
            effective_ratio = ratio

        adjusted_old = truncate_weight(old_weight * effective_ratio)
        difference = new_weight - adjusted_old

        if payload.trade_in_source == "LOCAL":
            if adjusted_old <= new_weight:
                subtotal = difference * sell_rate + labor
            else:
                subtotal = labor - (adjusted_old - new_weight) * buy_rate
        else:
            if adjusted_old <= new_weight:
                subtotal = (new_weight * sell_rate + labor) - adjusted_old * sell_rate
            else:
                subtotal = labor - (adjusted_old - new_weight) * buy_rate

    card_fee = subtotal * Decimal("0.05") if payload.is_credit_card and subtotal > 0 else Decimal("0")
    final_amount = round_twd_like_legacy(subtotal + card_fee)

    direction: Literal["CUSTOMER_PAYS", "STORE_REFUNDS", "ZERO"]
    if final_amount > 0:
        direction = "CUSTOMER_PAYS"
    elif final_amount < 0:
        direction = "STORE_REFUNDS"
    else:
        direction = "ZERO"

    return SalePricingResult(
        adjusted_old_weight=adjusted_old,
        weight_difference=difference,
        subtotal=subtotal,
        card_fee=card_fee,
        final_amount=final_amount,
        settlement_direction=direction,
    )
