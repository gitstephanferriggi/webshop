"""Outbound Bolt prices only; imported orders retain Bolt's charged amounts."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def markup_percentage(value):
    try:
        percent = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Bolt markup must be a non-negative percentage.") from None
    if not percent.is_finite() or percent < 0:
        raise ValueError("Bolt markup must be a non-negative percentage.")
    return percent


def selling_price(base_price, percent):
    base = Decimal(str(base_price))
    if not base.is_finite() or base <= 0:
        raise ValueError("Bolt requires a positive selling price.")
    result = (base * (1 + markup_percentage(percent) / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if result <= 0:
        raise ValueError("Bolt price rounds to zero.")
    return float(result)
