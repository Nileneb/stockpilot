"""Forecast services — within a tenant schema."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.catalog.models import Product
from apps.forecast.models import ForecastSnapshot
from apps.forecast.services import (
    compute_all_forecasts,
    compute_forecast,
    products_needing_reorder,
)
from apps.inventory.models import Stock, StockMovement


class ForecastServiceTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "acme.test.local"
        return domain

    def setUp(self):
        self.product = Product.objects.create(
            sku="P-1",
            name="Widget",
            reorder_point=5,
            reorder_quantity=10,
        )

    def _seed_consumption(self, *, daily_unit, days):
        now = timezone.now()
        for d in range(days):
            when = now - timedelta(days=d)
            m = StockMovement.objects.create(
                product=self.product,
                quantity_delta=Decimal(-daily_unit),
                kind=StockMovement.Kind.CONSUMPTION,
            )
            StockMovement.objects.filter(pk=m.pk).update(created_at=when)

    def test_zero_history(self):
        snap = compute_forecast(self.product, lookback_days=14)
        self.assertEqual(snap.daily_consumption_rate, Decimal("0.0000"))
        self.assertIsNone(snap.days_until_stockout)
        self.assertEqual(snap.suggested_reorder_quantity, Decimal("10"))

    def test_steady_consumption(self):
        Stock.adjust(
            product=self.product,
            delta=Decimal("100"),
            kind=StockMovement.Kind.MANUAL_IN,
        )
        self._seed_consumption(daily_unit=2, days=14)

        snap = compute_forecast(
            self.product,
            lookback_days=14,
            alpha=Decimal("0.5"),
            safety_days=2,
        )
        self.assertGreaterEqual(snap.daily_consumption_rate, Decimal("1.5"))
        self.assertLessEqual(snap.daily_consumption_rate, Decimal("2.5"))
        self.assertIsNotNone(snap.days_until_stockout)
        self.assertGreaterEqual(snap.suggested_reorder_quantity, Decimal("15"))

    def test_compute_all_forecasts_one_per_active_product(self):
        snaps = compute_all_forecasts()
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0].product, self.product)

    def test_products_needing_reorder(self):
        self.assertIn(self.product, list(products_needing_reorder()))
        Stock.adjust(
            product=self.product,
            delta=Decimal("100"),
            kind=StockMovement.Kind.MANUAL_IN,
        )
        self.assertNotIn(self.product, list(products_needing_reorder()))
