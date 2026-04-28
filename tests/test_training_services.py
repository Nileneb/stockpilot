"""Service-level training tests under a tenant schema.

Exercise the synchronous parts of `apps.training.services` end-to-end:
- ZIP import → Dataset + TrainingImages
- save_annotations validation
- freeze_dataset idempotence
- start_training_job preconditions
- YoloModel.activate() deactivates others atomically

Celery is forced into eager mode so `add_image` queues `generate_suggestions`
without trying to reach a broker. The suggestion task is monkey-patched to
a no-op so we don't load real ML models.
"""

from __future__ import annotations

import io
import zipfile
from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django_tenants.test.cases import TenantTestCase
from PIL import Image

from apps.training import services
from apps.training.models import Dataset, TrainingImage, TrainingJob, YoloModel


def _png_bytes(seed: int = 0) -> bytes:
    img = Image.new("RGB", (32, 32), color=(seed % 255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_yolo_zip(num_images: int = 2) -> bytes:
    """Build a YOLO-format zip in memory (images/, labels/, data.yaml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.yaml", "names:\n  0: bottle\n  1: can\n")
        for i in range(num_images):
            zf.writestr(f"images/img_{i}.png", _png_bytes(seed=i))
            zf.writestr(
                f"labels/img_{i}.txt",
                f"{i % 2} 0.5 0.5 0.4 0.4\n",
            )
    return buf.getvalue()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
)
class TrainingServicesTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme Training"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "training.test.local"
        return domain

    def setUp(self):
        # Replace the suggestion task with a no-op so eager Celery doesn't
        # reach for ultralytics/torch in unit tests.
        from apps.training import tasks as training_tasks

        self._real_generate = training_tasks.generate_suggestions
        training_tasks.generate_suggestions = type(
            "Noop", (), {"delay": staticmethod(lambda *a, **kw: None)}
        )()
        # services imports it lazily inside add_image — patch the alias too:
        services_mod = services  # for clarity
        # services.add_image does `from .tasks import generate_suggestions`
        # at call time, so the patch above on `tasks.generate_suggestions`
        # is what add_image actually picks up.

    def tearDown(self):
        from apps.training import tasks as training_tasks

        training_tasks.generate_suggestions = self._real_generate

    # --- ZIP import --------------------------------------------------------

    def test_create_dataset_from_zip_parses_yolo_layout(self):
        ds = services.create_dataset_from_zip(
            _build_yolo_zip(num_images=3),
            name="From ZIP",
        )
        self.assertEqual(ds.status, Dataset.Status.DRAFT)
        self.assertEqual(ds.images.count(), 3)
        # Labels resolve via data.yaml: img_0->bottle, img_1->can, img_2->bottle.
        labels = sorted(
            ann["label"]
            for img in ds.images.all()
            for ann in img.annotations
        )
        self.assertEqual(labels, ["bottle", "bottle", "can"])

    def test_create_dataset_from_zip_rejects_image_without_label(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("images/orphan.png", _png_bytes())
        with self.assertRaisesRegex(ValueError, "no matching .txt label"):
            services.create_dataset_from_zip(buf.getvalue(), name="bad")

    def test_create_dataset_from_zip_rejects_empty_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data.yaml", "names: []\n")
        with self.assertRaisesRegex(ValueError, "no images"):
            services.create_dataset_from_zip(buf.getvalue(), name="bad")

    # --- Annotation validation --------------------------------------------

    def _make_image(self, ds: Dataset) -> TrainingImage:
        ti = TrainingImage(dataset=ds)
        ti.image.save("x.png", ContentFile(_png_bytes()), save=False)
        ti.save()
        return ti

    def test_save_annotations_round_trips(self):
        ds = Dataset.objects.create(name="A")
        ti = self._make_image(ds)
        services.save_annotations(
            ti,
            [
                {
                    "label": "bottle",
                    "x_center": 0.5,
                    "y_center": 0.5,
                    "width": 0.2,
                    "height": 0.2,
                }
            ],
        )
        ti.refresh_from_db()
        self.assertEqual(len(ti.annotations), 1)
        self.assertEqual(ti.annotations[0]["label"], "bottle")

    def test_save_annotations_rejects_blank_label(self):
        ds = Dataset.objects.create(name="A")
        ti = self._make_image(ds)
        with self.assertRaisesRegex(ValueError, "non-empty label"):
            services.save_annotations(
                ti,
                [{"label": "  ", "x_center": 0.5, "y_center": 0.5, "width": 0.2, "height": 0.2}],
            )

    def test_save_annotations_rejects_out_of_range(self):
        ds = Dataset.objects.create(name="A")
        ti = self._make_image(ds)
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            services.save_annotations(
                ti,
                [{"label": "x", "x_center": 1.5, "y_center": 0.5, "width": 0.2, "height": 0.2}],
            )

    def test_save_annotations_rejects_zero_size(self):
        ds = Dataset.objects.create(name="A")
        ti = self._make_image(ds)
        with self.assertRaisesRegex(ValueError, "width and height must be > 0"):
            services.save_annotations(
                ti,
                [{"label": "x", "x_center": 0.5, "y_center": 0.5, "width": 0, "height": 0.2}],
            )

    # --- Freeze ------------------------------------------------------------

    def test_freeze_dataset_is_idempotent(self):
        ds = Dataset.objects.create(name="A")
        services.freeze_dataset(ds)
        first_frozen_at = Dataset.objects.get(pk=ds.pk).frozen_at
        self.assertIsNotNone(first_frozen_at)
        services.freeze_dataset(Dataset.objects.get(pk=ds.pk))
        # frozen_at must not be overwritten on the second call.
        self.assertEqual(Dataset.objects.get(pk=ds.pk).frozen_at, first_frozen_at)

    # --- Training job ------------------------------------------------------

    def test_start_training_job_rejects_dataset_without_annotations(self):
        ds = Dataset.objects.create(name="empty")
        self._make_image(ds)
        with self.assertRaisesRegex(ValueError, "no annotated images"):
            services.start_training_job(ds)

    def test_start_training_job_freezes_and_creates_job(self):
        # Suppress the actual training task from running (always-eager) by
        # swapping it for a noop just like generate_suggestions.
        from apps.training import tasks as training_tasks

        real_train = training_tasks.train_yolo
        training_tasks.train_yolo = type(
            "Noop", (), {"delay": staticmethod(lambda *a, **kw: None)}
        )()
        try:
            ds = Dataset.objects.create(name="trainable")
            ti = self._make_image(ds)
            services.save_annotations(
                ti,
                [{"label": "bottle", "x_center": 0.5, "y_center": 0.5, "width": 0.2, "height": 0.2}],
            )
            job = services.start_training_job(ds, epochs=1, batch_size=1, image_size=64)
        finally:
            training_tasks.train_yolo = real_train

        ds.refresh_from_db()
        self.assertEqual(ds.status, Dataset.Status.FROZEN)
        self.assertEqual(job.status, TrainingJob.Status.PENDING)
        self.assertEqual(job.epochs, 1)

    # --- Activate model ----------------------------------------------------

    def test_activate_model_deactivates_others(self):
        m1 = YoloModel.objects.create(
            name="m1", version=1, file="models/test/m1.pt", is_active=True
        )
        m2 = YoloModel.objects.create(
            name="m2", version=2, file="models/test/m2.pt", is_active=False
        )
        services.activate_model(m2)
        m1.refresh_from_db()
        m2.refresh_from_db()
        self.assertFalse(m1.is_active)
        self.assertTrue(m2.is_active)

    def test_activate_model_when_already_active_keeps_only_one(self):
        m1 = YoloModel.objects.create(
            name="m1", version=1, file="models/test/m1.pt", is_active=True
        )
        services.activate_model(m1)
        self.assertEqual(
            YoloModel.objects.filter(is_active=True).count(), 1
        )


class InferenceUsesActiveModelTests(TenantTestCase):
    """Per-tenant inference resolution under a real schema."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme Inference"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "inference.test.local"
        return domain

    def test_resolve_path_returns_active_model_file(self):
        from apps.vision.inference import UltralyticsBackend

        # Create an active YoloModel pointing at a fake file.
        ym = YoloModel(name="acme-v1", version=1, is_active=True)
        ym.file.save("test_weights.pt", ContentFile(b"\x00\x01"), save=False)
        ym.save()

        backend = UltralyticsBackend()
        path = backend._resolve_path()
        self.assertTrue(path.endswith("test_weights.pt"))

    @override_settings(VISION_YOLO_MODEL="default.pt")
    def test_resolve_path_falls_back_when_no_active_model(self):
        from apps.vision.inference import UltralyticsBackend

        # No active YoloModel exists -> default.
        self.assertEqual(YoloModel.objects.filter(is_active=True).count(), 0)
        backend = UltralyticsBackend()
        self.assertEqual(backend._resolve_path(), "default.pt")
