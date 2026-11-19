"""Legacy-compatible rounding rules for jewelry transactions.

The old application truncates adjusted trade-in weight to two decimal places,
then rounds the final TWD amount like JavaScript Math.round (floor(x + 0.5)).
"""
from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR

WEIGHT_QUANTUM = Decimal("0.01")
MONEY_QUANTUM = Decimal("1")


def as_decimal(value: Decimal | int | str) -> Decimal:
    """Convert supported inputs without introducing binary float artifacts."""
    if isinstance(value, float):
        raise TypeError("請使用 Decimal、整數或字串傳入計價數值。")
    return value if isinstance(value, Decimal) else Decimal(value)


def truncate_weight(value: Decimal) -> Decimal:
    """Truncate weight to 2 decimal places, matching legacy positive weights."""
    return value.quantize(WEIGHT_QUANTUM, rounding=ROUND_DOWN)


def round_twd_like_legacy(value: Decimal) -> Decimal:
    """Match JavaScript Math.round: floor(value + 0.5), including negatives."""
    return (value + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)
