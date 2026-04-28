from django.db import models

from apps.tenants.managers import OrgScopedModel


class Supplier(OrgScopedModel):
    name = models.CharField(max_length=140)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    lead_time_days = models.PositiveIntegerField(
        default=7,
        help_text="Typical days from order to delivery.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"),
                name="unique_supplier_name_per_org",
            )
        ]
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Product(OrgScopedModel):
    class Unit(models.TextChoices):
        PIECE = "piece", "Piece"
        KG = "kg", "Kilogram"
        L = "l", "Liter"
        PACK = "pack", "Pack"

    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=8, choices=Unit.choices, default=Unit.PIECE)
    default_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_products",
    )
    reorder_point = models.PositiveIntegerField(
        default=0,
        help_text="Stock level at which a reorder should be triggered.",
    )
    reorder_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Default quantity to reorder when triggered.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "sku"),
                name="unique_sku_per_org",
            )
        ]
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"
