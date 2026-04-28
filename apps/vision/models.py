from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.catalog.models import Product
from apps.tenants.managers import OrgScopedModel


def _photo_upload_path(instance: "InventoryPhoto", filename: str) -> str:
    return f"photos/{instance.organization_id}/{filename}"


class InventoryPhoto(OrgScopedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        APPLIED = "applied", "Applied to stock"
        FAILED = "failed", "Failed"

    image = models.ImageField(upload_to=_photo_upload_path)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_photos",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.UPLOADED,
    )
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Photo {self.pk} ({self.status})"


class Detection(OrgScopedModel):
    photo = models.ForeignKey(
        InventoryPhoto,
        on_delete=models.CASCADE,
        related_name="detections",
    )
    label = models.CharField(max_length=64)
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    bbox_x = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    bbox_y = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    bbox_w = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    bbox_h = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-confidence",)
        indexes = [models.Index(fields=("organization", "photo", "label"))]

    def __str__(self) -> str:
        return f"{self.label} ({self.confidence})"


class ProductLabel(OrgScopedModel):
    """Maps a YOLO class label to a Product within an organization.

    `multiplier` lets one detection represent N stock units (e.g. a six-pack).
    """

    label = models.CharField(max_length=64)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="labels",
    )
    multiplier = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal("1"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "label"),
                name="unique_label_per_org",
            )
        ]
        ordering = ("label",)

    def __str__(self) -> str:
        return f"{self.label} → {self.product.sku} (×{self.multiplier})"
