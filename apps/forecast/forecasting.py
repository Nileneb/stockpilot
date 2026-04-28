"""Pure-function forecasting math.

Kept separate from services.py / models.py so the math is easily unit-tested
without DB or Django setup.
"""

from __future__ import annotations

from decimal import Decimal


def simple_exponential_smoothing(
    series: list[Decimal],
    alpha: Decimal = Decimal("0.3"),
) -> Decimal:
    """Return the latest smoothed value of `series`.

    `series` is ordered oldest → newest. Empty series returns 0.
    Single value returns the value itself.

    Formula: S_t = α·X_t + (1-α)·S_{t-1}, with S_0 = X_0.
    """
    if not series:
        return Decimal("0")
    s = Decimal(series[0])
    one_minus = Decimal("1") - Decimal(alpha)
    a = Decimal(alpha)
    for x in series[1:]:
        s = a * Decimal(x) + one_minus * s
    return s


def days_until_stockout(
    current_stock: Decimal,
    daily_rate: Decimal,
) -> Decimal | None:
    """Return days the current stock will last at `daily_rate`. None if rate=0."""
    if daily_rate <= 0:
        return None
    if current_stock <= 0:
        return Decimal("0")
    return Decimal(current_stock) / Decimal(daily_rate)


def suggested_reorder_quantity(
    daily_rate: Decimal,
    lead_time_days: int,
    safety_days: int,
    minimum_quantity: Decimal,
) -> Decimal:
    """Compute suggested order qty: covers lead time + safety buffer, but
    never below the product's configured `reorder_quantity`."""
    horizon = Decimal(lead_time_days + safety_days)
    forecast_need = (Decimal(daily_rate) * horizon).quantize(Decimal("1"))
    return max(Decimal(minimum_quantity), forecast_need)
