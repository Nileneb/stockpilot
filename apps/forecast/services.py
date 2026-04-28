"""Forecast services — bridge between Django models and pure forecasting math."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Product
from apps.inventory.models import Stock, StockMovement
from apps.tenants.models import Organization

from . import forecasting
from .models import ForecastSnapshot


def _daily_consumption_series(
    product: Product,
    lookback_days: int,
) -> list[Decimal]:
    """Return [c_{N-1}, c_{N-2}, ..., c_0] — units consumed per day,
    oldest first. Each entry is the absolute value of net negative deltas
    from CONSUMPTION movements on that day."""
    today = timezone.now().date()
    start = today - timedelta(days=lookback_days - 1)

    rows = (
        StockMovement.all_objects.filter(
            organization=product.organization,
            product=product,
            kind=StockMovement.Kind.CONSUMPTION,
            created_at__date__gte=start,
            created_at__date__lte=today,
        )
        .extra(select={"day": "date(created_at)"})
        .values("day")
        .annotate(total=Sum("quantity_delta"))
    )
    by_day: dict = {row["day"]: row["total"] for row in rows}

    series: list[Decimal] = []
    for i in range(lookback_days):
        day = start + timedelta(days=i)
        # Match either date object or stringified date (SQLite extra returns str)
        total = by_day.get(day) or by_day.get(day.isoformat()) or Decimal("0")
        consumed = abs(Decimal(total)) if Decimal(total) < 0 else Decimal("0")
        series.append(consumed)
    return series


def compute_forecast(
    product: Product,
    *,
    lookback_days: int = 30,
    alpha: Decimal = Decimal("0.3"),
    safety_days: int = 2,
) -> ForecastSnapshot:
    series = _daily_consumption_series(product, lookback_days)
    rate = forecasting.simple_exponential_smoothing(series, alpha=alpha)

    try:
        stock = Stock.all_objects.get(
            organization=product.organization, product=product
        )
        current_stock = stock.quantity_on_hand
    except Stock.DoesNotExist:
        current_stock = Decimal("0")

    dts = forecasting.days_until_stockout(current_stock, rate)

    lead_time = (
        product.default_supplier.lead_time_days
        if product.default_supplier_id
        else 7
    )
    suggested = forecasting.suggested_reorder_quantity(
        daily_rate=rate,
        lead_time_days=lead_time,
        safety_days=safety_days,
        minimum_quantity=Decimal(product.reorder_quantity),
    )

    return ForecastSnapshot.objects.create(
        organization=product.organization,
        product=product,
        lookback_days=lookback_days,
        method="exp_smoothing",
        alpha=alpha,
        daily_consumption_rate=rate.quantize(Decimal("0.0001")),
        days_until_stockout=(
            dts.quantize(Decimal("0.01")) if dts is not None else None
        ),
        suggested_reorder_quantity=suggested,
        current_stock=current_stock,
    )


def compute_all_forecasts(
    organization: Organization,
    **kwargs,
) -> list[ForecastSnapshot]:
    snapshots: list[ForecastSnapshot] = []
    for product in Product.all_objects.filter(
        organization=organization, is_active=True
    ):
        snapshots.append(compute_forecast(product, **kwargs))
    return snapshots


def products_needing_reorder(organization: Organization) -> Iterable[Product]:
    """Products whose current stock is at or below their reorder_point."""
    return [
        p
        for p in Product.all_objects.filter(
            organization=organization, is_active=True
        ).select_related("default_supplier")
        if _current_stock(p) <= Decimal(p.reorder_point)
    ]


def _current_stock(product: Product) -> Decimal:
    try:
        return Stock.all_objects.get(
            organization=product.organization, product=product
        ).quantity_on_hand
    except Stock.DoesNotExist:
        return Decimal("0")
