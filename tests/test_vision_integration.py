"""Integration test that exercises the real UltralyticsBackend.

Marked `integration` because it loads a YOLO model (downloads weights on
first run, ~6 MB for yolo11n.pt). Run with `pytest -m integration` or as
part of the full suite.
"""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

from apps.tenants.managers import clear_active_organization
from apps.vision.inference import UltralyticsBackend
from apps.vision.models import Detection, InventoryPhoto
from apps.vision.services import run_inference

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_active_org():
    clear_active_organization()
    yield
    clear_active_organization()


def _synthetic_jpg() -> bytes:
    """A 640x480 JPEG with some shapes — enough to exercise the model end-to-end.

    Returns very few or zero detections because the model is trained on real
    photos, but proves the pipeline works without errors.
    """
    img = Image.new("RGB", (640, 480), color=(40, 60, 80))
    d = ImageDraw.Draw(img)
    for x, y in [(60, 60), (200, 60), (340, 60), (480, 60),
                 (60, 200), (200, 200), (340, 200), (480, 200)]:
        d.ellipse([x, y, x + 80, y + 80], fill=(180, 30, 30))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def test_ultralytics_backend_loads_and_runs(tmp_path):
    """Real backend can be instantiated, model loads, detect() returns a list."""
    backend = UltralyticsBackend()
    p = tmp_path / "synthetic.jpg"
    p.write_bytes(_synthetic_jpg())
    results = backend.detect(str(p))
    assert isinstance(results, list)
    # No assertion on count: synthetic input may yield 0; the point is that
    # the wiring (model load + detect call + result parsing) works.
    for r in results:
        assert isinstance(r.label, str)
        assert 0.0 <= r.confidence <= 1.0
        if r.bbox is not None:
            assert len(r.bbox) == 4


def test_run_inference_with_real_backend(org_a, settings):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.UltralyticsBackend"
    file = SimpleUploadedFile(
        "shelf.jpg", _synthetic_jpg(), content_type="image/jpeg"
    )
    photo = InventoryPhoto.all_objects.create(organization=org_a, image=file)
    n = run_inference(photo)
    photo.refresh_from_db()
    assert photo.status == InventoryPhoto.Status.PROCESSED
    assert photo.processed_at is not None
    assert Detection.all_objects.filter(photo=photo).count() == n
