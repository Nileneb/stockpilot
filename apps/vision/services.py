"""Application services for the vision pipeline."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import Stock, StockMovement

from .inference import get_backend
from .models import Detection, InventoryPhoto, ProductLabel


def run_inference(photo: InventoryPhoto) -> int:
    """Run the configured backend on the photo, persist Detection rows.

    Returns the number of detections created. Idempotent: re-running clears
    previous detections for the photo first.
    """
    with transaction.atomic():
        photo.status = InventoryPhoto.Status.PROCESSING
        photo.error = ""
        photo.save(update_fields=["status", "error"])
        Detection.objects.filter(photo=photo).delete()

    try:
        backend = get_backend()
        results = backend.detect(photo.image.path)
    except Exception as exc:  # noqa: BLE001
        photo.status = InventoryPhoto.Status.FAILED
        photo.error = f"{type(exc).__name__}: {exc}"
        photo.save(update_fields=["status", "error"])
        raise

    with transaction.atomic():
        rows = [
            Detection(
                photo=photo,
                label=r.label,
                confidence=Decimal(str(r.confidence)),
                bbox_x=None if r.bbox is None else Decimal(str(round(r.bbox[0], 4))),
                bbox_y=None if r.bbox is None else Decimal(str(round(r.bbox[1], 4))),
                bbox_w=None if r.bbox is None else Decimal(str(round(r.bbox[2], 4))),
                bbox_h=None if r.bbox is None else Decimal(str(round(r.bbox[3], 4))),
            )
            for r in results
        ]
        Detection.objects.bulk_create(rows)

        photo.status = InventoryPhoto.Status.PROCESSED
        photo.processed_at = timezone.now()
        photo.save(update_fields=["status", "processed_at"])

    return len(rows)


@transaction.atomic
def apply_to_stock(photo: InventoryPhoto, performed_by=None) -> dict[str, dict]:
    """Group detections by label, map via ProductLabel, adjust stock.

    Returns a report keyed by label:
        {label: {"count": N, "matched": True|False, "movement_id": id_or_None}}
    """
    if photo.status not in (
        InventoryPhoto.Status.PROCESSED,
        InventoryPhoto.Status.APPLIED,
    ):
        raise ValueError(
            f"Photo must be processed before applying (status={photo.status})"
        )

    counts: dict[str, int] = {}
    for det in Detection.objects.filter(photo=photo):
        counts[det.label] = counts.get(det.label, 0) + 1

    mappings = {pl.label: pl for pl in ProductLabel.objects.all()}

    report: dict[str, dict] = {}
    for label, count in counts.items():
        mapping = mappings.get(label)
        if mapping is None:
            report[label] = {"count": count, "matched": False, "movement_id": None}
            continue
        delta = Decimal(count) * mapping.multiplier
        movement = Stock.adjust(
            product=mapping.product,
            delta=delta,
            kind=StockMovement.Kind.PHOTO_COUNT,
            performed_by=performed_by,
            note=f"From photo #{photo.pk}",
            is_count=True,
        )
        report[label] = {
            "count": count,
            "matched": True,
            "movement_id": movement.pk,
        }

    photo.status = InventoryPhoto.Status.APPLIED
    photo.applied_at = timezone.now()
    photo.save(update_fields=["status", "applied_at"])

    return report
