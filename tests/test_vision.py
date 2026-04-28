"""Vision pipeline: stub backend, run_inference, apply_to_stock."""

from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.inventory.models import Stock, StockMovement
from apps.tenants.managers import clear_active_organization
from apps.vision.inference import (
    DetectionResult,
    StubBackend,
    aggregate_by_label,
)
from apps.vision.models import Detection, InventoryPhoto, ProductLabel
from apps.vision.services import apply_to_stock, run_inference


@pytest.fixture(autouse=True)
def _no_active_org():
    clear_active_organization()
    yield
    clear_active_organization()


def _png_bytes(seed: int = 0) -> bytes:
    img = Image.new("RGB", (32, 32), color=(seed % 255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_photo(org, raw: bytes | None = None) -> InventoryPhoto:
    file = SimpleUploadedFile(
        "shelf.png",
        raw or _png_bytes(),
        content_type="image/png",
    )
    return InventoryPhoto.all_objects.create(organization=org, image=file)


# ---- StubBackend deterministic ----


def test_stub_backend_is_deterministic(tmp_path):
    raw = _png_bytes(seed=42)
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    p1.write_bytes(raw)
    p2.write_bytes(raw)

    backend = StubBackend()
    assert backend.detect(str(p1)) == backend.detect(str(p2))


def test_stub_backend_different_files_can_differ(tmp_path):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    p1.write_bytes(_png_bytes(seed=1))
    p2.write_bytes(_png_bytes(seed=200))
    # Not strictly required to differ, but with two distinct seeds the
    # SHA-1 first byte usually does. We still assert both return ≥1 detection.
    assert StubBackend().detect(str(p1))
    assert StubBackend().detect(str(p2))


def test_aggregate_by_label_counts():
    detections = [
        DetectionResult("bottle", 0.9),
        DetectionResult("bottle", 0.8),
        DetectionResult("can", 0.7),
    ]
    assert aggregate_by_label(detections) == {"bottle": 2, "can": 1}


# ---- run_inference ----


def test_run_inference_persists_detections_and_marks_processed(org_a, settings):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    photo = _make_photo(org_a)
    n = run_inference(photo)
    photo.refresh_from_db()
    assert n > 0
    assert photo.status == InventoryPhoto.Status.PROCESSED
    assert photo.processed_at is not None
    assert Detection.all_objects.filter(photo=photo).count() == n


def test_run_inference_is_idempotent_clears_old_detections(org_a, settings):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    photo = _make_photo(org_a)
    run_inference(photo)
    first_count = Detection.all_objects.filter(photo=photo).count()
    run_inference(photo)
    assert Detection.all_objects.filter(photo=photo).count() == first_count


def test_run_inference_marks_failed_on_backend_error(org_a, settings, monkeypatch):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    photo = _make_photo(org_a)

    def boom(self, image_path):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(StubBackend, "detect", boom)
    with pytest.raises(RuntimeError):
        run_inference(photo)
    photo.refresh_from_db()
    assert photo.status == InventoryPhoto.Status.FAILED
    assert "backend exploded" in photo.error


# ---- apply_to_stock ----


def test_apply_to_stock_uses_mapping_and_multiplier(org_a, product_a, settings):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    photo = _make_photo(org_a)
    run_inference(photo)
    # Pick the actual label the stub returned and map it
    label = Detection.all_objects.filter(photo=photo).first().label
    ProductLabel.all_objects.create(
        organization=org_a,
        label=label,
        product=product_a,
        multiplier=Decimal("2"),
    )
    expected_count = Detection.all_objects.filter(
        photo=photo, label=label
    ).count()

    report = apply_to_stock(photo)
    photo.refresh_from_db()

    assert photo.status == InventoryPhoto.Status.APPLIED
    assert photo.applied_at is not None
    assert report[label]["matched"] is True
    assert report[label]["count"] == expected_count

    stock = Stock.all_objects.get(product=product_a)
    assert stock.quantity_on_hand == Decimal(expected_count) * Decimal("2")
    assert stock.last_counted_at is not None
    movements = StockMovement.all_objects.filter(product=product_a)
    assert movements.count() == 1
    assert movements.first().kind == StockMovement.Kind.PHOTO_COUNT


def test_apply_to_stock_skips_unmapped_labels(org_a, settings):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    photo = _make_photo(org_a)
    run_inference(photo)
    report = apply_to_stock(photo)
    # No ProductLabel mapping → all unmatched
    for entry in report.values():
        assert entry["matched"] is False
        assert entry["movement_id"] is None
    # No StockMovement created
    assert StockMovement.all_objects.count() == 0


def test_apply_to_stock_does_not_use_other_orgs_mapping(
    org_a, org_b, product_a, product_b, settings
):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    photo = _make_photo(org_a)
    run_inference(photo)
    label = Detection.all_objects.filter(photo=photo).first().label

    # Mapping exists in org_b, NOT org_a — must not match
    ProductLabel.all_objects.create(
        organization=org_b, label=label, product=product_b
    )

    report = apply_to_stock(photo)
    assert all(not r["matched"] for r in report.values())
    assert StockMovement.all_objects.count() == 0


def test_apply_to_stock_rejects_unprocessed_photo(org_a):
    photo = _make_photo(org_a)
    with pytest.raises(ValueError):
        apply_to_stock(photo)
