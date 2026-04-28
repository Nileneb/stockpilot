from decimal import Decimal

from django.db import models

from apps.catalog.models import Product
from apps.tenants.managers import OrgScopedModel


class ForecastSnapshot(OrgScopedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="forecasts",
    )
    lookback_days = models.PositiveIntegerField()
    method = models.CharField(max_length=32, default="exp_smoothing")
    alpha = models.DecimalField(max_digits=4, decimal_places=3)
    daily_consumption_rate = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
    )
    days_until_stockout = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="NULL when consumption rate is 0.",
    )
    suggested_reorder_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0"),
    )
    current_stock = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "product", "-created_at")),
        ]

    def __str__(self) -> str:
        return (
            f"{self.product.sku} rate={self.daily_consumption_rate}/d "
            f"@ {self.created_at:%Y-%m-%d}"
        )
