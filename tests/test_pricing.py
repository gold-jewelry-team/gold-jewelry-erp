from decimal import Decimal

import pytest

from app.services.pricing.purchases import PurchaseCostInput, calculate_purchase_cost
from app.services.pricing.rounding import round_twd_like_legacy, truncate_weight
from app.services.pricing.sales import SalePricingInput, calculate_sale_amount


D = Decimal


def test_new_gold_sale_without_trade_in():
    result = calculate_sale_amount(SalePricingInput(
        new_weight=D("2"), sell_gold_price=D("12000"),
        buy_gold_price=D("11000"), labor_fee=D("800"),
    ))
    assert result.subtotal == D("24800")
    assert result.final_amount == D("24800")
    assert result.adjusted_old_weight == D("0")


def test_local_trade_in_less_than_new_weight():
    result = calculate_sale_amount(SalePricingInput(
        new_weight=D("2"), sell_gold_price=D("12000"),
        buy_gold_price=D("11000"), labor_fee=D("800"),
        has_trade_in=True, trade_in_source="LOCAL", old_weight=D("1.25"),
    ))
    assert result.adjusted_old_weight == D("1.25")
    assert result.subtotal == D("9800")
    assert result.final_amount == D("9800")


def test_local_trade_in_exceeds_new_weight_and_store_refunds():
    result = calculate_sale_amount(SalePricingInput(
        new_weight=D("1"), sell_gold_price=D("12000"),
        buy_gold_price=D("11000"), labor_fee=D("500"),
        has_trade_in=True, trade_in_source="LOCAL", old_weight=D("1.5"),
    ))
    assert result.subtotal == D("-5000")
    assert result.final_amount == D("-5000")
    assert result.settlement_direction == "STORE_REFUNDS"


def test_external_trade_in_uses_ratio_and_truncates_weight():
    result = calculate_sale_amount(SalePricingInput(
        new_weight=D("2"), sell_gold_price=D("12000"),
        buy_gold_price=D("11000"), labor_fee=D("800"),
        has_trade_in=True, trade_in_source="EXTERNAL",
        old_weight=D("1.333"), trade_in_ratio=D("0.95"),
    ))
    assert result.adjusted_old_weight == D("1.26")
    assert result.subtotal == D("9680.00")
    assert result.final_amount == D("9680")


def test_external_trade_in_excess_uses_buy_price_for_excess():
    result = calculate_sale_amount(SalePricingInput(
        new_weight=D("1"), sell_gold_price=D("12000"),
        buy_gold_price=D("11000"), labor_fee=D("500"),
        has_trade_in=True, trade_in_source="EXTERNAL",
        old_weight=D("2"), trade_in_ratio=D("0.95"),
    ))
    assert result.adjusted_old_weight == D("1.90")
    assert result.subtotal == D("-9400.00")


def test_card_fee_only_applies_to_positive_subtotal():
    positive = calculate_sale_amount(SalePricingInput(
        new_weight=D("1"), sell_gold_price=D("10000"),
        buy_gold_price=D("9000"), labor_fee=D("0"), is_credit_card=True,
    ))
    negative = calculate_sale_amount(SalePricingInput(
        new_weight=D("1"), sell_gold_price=D("10000"),
        buy_gold_price=D("9000"), labor_fee=D("0"),
        has_trade_in=True, trade_in_source="LOCAL",
        old_weight=D("1.5"), is_credit_card=True,
    ))
    assert positive.card_fee == D("500.00")
    assert positive.final_amount == D("10500")
    assert negative.card_fee == D("0")


def test_purchase_cash_buy():
    assert calculate_purchase_cost(PurchaseCostInput(
        mode="CASH_BUY", in_weight=D("2"), out_weight=D("0"),
        gold_price=D("12000"), labor_fee=D("300"),
    )) == D("24300")


def test_purchase_weight_exchange():
    assert calculate_purchase_cost(PurchaseCostInput(
        mode="WEIGHT_EXCHANGE", in_weight=D("3"), out_weight=D("1.5"),
        gold_price=D("12000"), labor_fee=D("300"),
    )) == D("18300")


def test_legacy_rounding_matches_math_round_for_negative_half():
    assert round_twd_like_legacy(D("10.5")) == D("11")
    assert round_twd_like_legacy(D("-10.5")) == D("-10")


def test_weight_truncation():
    assert truncate_weight(D("1.239")) == D("1.23")


def test_invalid_trade_in_is_rejected():
    with pytest.raises(ValueError):
        calculate_sale_amount(SalePricingInput(
            new_weight=D("1"), sell_gold_price=D("10000"),
            buy_gold_price=D("9000"), has_trade_in=True,
            trade_in_source="LOCAL", old_weight=D("0"),
        ))
