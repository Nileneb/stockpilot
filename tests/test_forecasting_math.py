"""Pure math tests for the forecasting helpers (no DB)."""

from decimal import Decimal

import pytest

from apps.forecast.forecasting import (
    days_until_stockout,
    simple_exponential_smoothing,
    suggested_reorder_quantity,
)


def test_es_empty_series_is_zero():
    assert simple_exponential_smoothing([]) == Decimal("0")


def test_es_single_value_returns_value():
    assert simple_exponential_smoothing([Decimal("7")]) == Decimal("7")


def test_es_constant_series_converges_to_value():
    series = [Decimal("5")] * 20
    s = simple_exponential_smoothing(series, alpha=Decimal("0.3"))
    # Constant input → smoothed value equals the constant exactly.
    assert s == Decimal("5")


def test_es_recent_values_weight_more():
    series = [Decimal("0")] * 9 + [Decimal("100")]
    # alpha 0.5: last point heavily weighted, but not 100 outright
    s = simple_exponential_smoothing(series, alpha=Decimal("0.5"))
    assert Decimal("0") < s < Decimal("100")
    # alpha 1.0: only last value matters
    s_full = simple_exponential_smoothing(series, alpha=Decimal("1.0"))
    assert s_full == Decimal("100")


def test_days_until_stockout_zero_rate_is_none():
    assert days_until_stockout(Decimal("100"), Decimal("0")) is None


def test_days_until_stockout_zero_stock_is_zero():
    assert days_until_stockout(Decimal("0"), Decimal("5")) == Decimal("0")


def test_days_until_stockout_basic():
    assert days_until_stockout(Decimal("50"), Decimal("5")) == Decimal("10")


def test_suggested_reorder_uses_minimum_when_forecast_low():
    qty = suggested_reorder_quantity(
        daily_rate=Decimal("0.1"),
        lead_time_days=7,
        safety_days=2,
        minimum_quantity=Decimal("20"),
    )
    # 0.1 * 9 = 0.9 → below minimum 20 → 20 wins
    assert qty == Decimal("20")


def test_suggested_reorder_uses_forecast_when_high():
    qty = suggested_reorder_quantity(
        daily_rate=Decimal("10"),
        lead_time_days=7,
        safety_days=3,
        minimum_quantity=Decimal("5"),
    )
    # 10 * 10 = 100 → wins over min 5
    assert qty == Decimal("100")
