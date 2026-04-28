from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.tenants.managers import OrgScopedModel


class Stock(OrgScopedModel):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="stock",
    )
    quantity_on_hand = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0"),
    )
    last_counted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "product"),
                name="unique_stock_per_product",
            )
        ]
        ordering = ("product__name",)

    def __str__(self) -> str:
        return f"{self.product.sku}: {self.quantity_on_hand}"

    @classmethod
    @transaction.atomic
    def adjust(
        cls,
        *,
        product: Product,
        delta: Decimal,
        kind: "StockMovement.Kind",
        performed_by=None,
        note: str = "",
        is_count: bool = False,
    ) -> "StockMovement":
        """Atomically apply a quantity delta and append a StockMovement.

        Use `is_count=True` when delta represents a fresh inventory count
        (sets last_counted_at). Otherwise delta is a relative change.
        """
        stock, _ = cls.all_objects.select_for_update().get_or_create(
            organization=product.organization,
            product=product,
            defaults={"quantity_on_hand": Decimal("0")},
        )
        stock.quantity_on_hand = stock.quantity_on_hand + Decimal(delta)
        if is_count:
            stock.last_counted_at = timezone.now()
        stock.save()

        return StockMovement.objects.create(
            organization=product.organization,
            product=product,
            quantity_delta=Decimal(delta),
            kind=kind,
            performed_by=performed_by,
            note=note,
        )


class StockMovement(OrgScopedModel):
    class Kind(models.TextChoices):
        COUNT_CORRECTION = "count_correction", "Count correction"
        MANUAL_IN = "manual_in", "Manual in"
        MANUAL_OUT = "manual_out", "Manual out"
        PHOTO_COUNT = "photo_count", "Photo count"
        ORDER_RECEIVED = "order_received", "Order received"
        CONSUMPTION = "consumption", "Consumption"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="movements",
    )
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "product", "-created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.product.sku} {self.quantity_delta:+} ({self.kind})"
