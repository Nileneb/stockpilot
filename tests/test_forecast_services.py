"""Forecast services that touch the DB (StockMovement, Stock, ForecastSnapshot)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.forecast.models import ForecastSnapshot
from apps.forecast.services import (
    compute_all_forecasts,
    compute_forecast,
    products_needing_reorder,
)
from apps.inventory.models import Stock, StockMovement
from apps.tenants.managers import (
    clear_active_organization,
    set_active_organization,
)


@pytest.fixture(autouse=True)
def _no_active_org():
    clear_active_organization()
    yield
    clear_active_organization()


def _seed_consumption(product, *, daily_unit, days):
    """Create CONSUMPTION movements at -daily_unit per day for the past `days` days."""
    now = timezone.now()
    for d in range(days):
        when = now - timedelta(days=d)
        m = StockMovement.objects.create(
            organization=product.organization,
            product=product,
            quantity_delta=Decimal(-daily_unit),
            kind=StockMovement.Kind.CONSUMPTION,
        )
        # Override auto_now_add to backdate the movement
        StockMovement.all_objects.filter(pk=m.pk).update(created_at=when)


def test_compute_forecast_zero_history(product_a):
    snap = compute_forecast(product_a, lookback_days=14)
    assert snap.daily_consumption_rate == Decimal("0.0000")
    assert snap.days_until_stockout is None
    # Suggested falls back to product.reorder_quantity (10)
    assert snap.suggested_reorder_quantity == Decimal("10")


def test_compute_forecast_steady_consumption(product_a):
    Stock.adjust(
        product=product_a,
        delta=Decimal("100"),
        kind=StockMovement.Kind.MANUAL_IN,
    )
    _seed_consumption(product_a, daily_unit=2, days=14)

    snap = compute_forecast(
        product_a,
        lookback_days=14,
        alpha=Decimal("0.5"),
        safety_days=2,
    )
    # Daily rate should be ~2 (steady state)
    assert Decimal("1.5") <= snap.daily_consumption_rate <= Decimal("2.5")
    # Stock 100 / rate ~2 → ~50 days
    assert snap.days_until_stockout is not None
    assert Decimal("40") <= snap.days_until_stockout <= Decimal("70")
    # rate * (lead_time 7 + safety 2) = ~18, > min 10 → suggested ~18
    assert snap.suggested_reorder_quantity >= Decimal("15")


def test_compute_forecast_persists_org(product_a, org_a):
    snap = compute_forecast(product_a)
    assert snap.organization_id == org_a.id


def test_compute_all_forecasts_one_per_product(org_a, product_a):
    snaps = compute_all_forecasts(org_a)
    assert len(snaps) == 1
    assert snaps[0].product == product_a


def test_compute_all_forecasts_org_scoped(org_a, org_b, product_a, product_b):
    snaps_a = compute_all_forecasts(org_a)
    snaps_b = compute_all_forecasts(org_b)
    assert {s.product_id for s in snaps_a} == {product_a.id}
    assert {s.product_id for s in snaps_b} == {product_b.id}


def test_products_needing_reorder(product_a):
    # Stock 0, reorder_point 5 → should appear
    assert product_a in list(products_needing_reorder(product_a.organization))

    # Push stock above reorder_point
    Stock.adjust(
        product=product_a,
        delta=Decimal("100"),
        kind=StockMovement.Kind.MANUAL_IN,
    )
    assert product_a not in list(products_needing_reorder(product_a.organization))


def test_forecast_snapshot_org_scoped_in_default_manager(org_a, product_a, org_b):
    compute_forecast(product_a)
    set_active_organization(org_a)
    assert ForecastSnapshot.objects.count() == 1
    set_active_organization(org_b)
    assert ForecastSnapshot.objects.count() == 0
