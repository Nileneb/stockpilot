"""Celery tasks for the training pipeline."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import traceback
from pathlib import Path

import yaml
from celery import shared_task
from django.utils import timezone
from django_tenants.utils import schema_context

from .models import Dataset, TrainingImage, TrainingJob, YoloModel
from .suggestions import generate_for_image_path

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def generate_suggestions(self, image_id: int, schema_name: str):
    """Run YOLO11x + SAM on a TrainingImage, persist results.

    Run inside the tenant schema. Failures are recorded on the row but do
    not raise (the user can still annotate manually).
    """
    with schema_context(schema_name):
        try:
            image = TrainingImage.objects.get(pk=image_id)
        except TrainingImage.DoesNotExist:
            logger.warning("TrainingImage %s vanished before suggestions ran", image_id)
            return

        image.suggestions_status = TrainingImage.SuggestionsStatus.RUNNING
        image.suggestions_error = ""
        image.save(update_fields=["suggestions_status", "suggestions_error"])

        try:
            suggestions = generate_for_image_path(image.image.path)
            image.auto_suggestions = [s.to_json() for s in suggestions]
            image.suggestions_status = TrainingImage.SuggestionsStatus.DONE
        except Exception as exc:  # noqa: BLE001
            logger.exception("Suggestion run failed for image %s", image_id)
            image.suggestions_status = TrainingImage.SuggestionsStatus.FAILED
            image.suggestions_error = f"{type(exc).__name__}: {exc}"
        image.save(
            update_fields=[
                "auto_suggestions",
                "suggestions_status",
                "suggestions_error",
            ]
        )


@shared_task(bind=True)
def train_yolo(self, job_id: int, schema_name: str):
    """End-to-end YOLO fine-tuning task.

    Steps:
    1. tenant_context(schema_name)
    2. Materialize dataset to a tmpdir as YOLO data layout.
    3. Run ultralytics.YOLO(base).train(...).
    4. Copy best.pt into media/models/<schema>/, register a YoloModel.
    """
    from importlib import import_module

    with schema_context(schema_name):
        try:
            job = TrainingJob.objects.get(pk=job_id)
        except TrainingJob.DoesNotExist:
            logger.warning("TrainingJob %s vanished before training", job_id)
            return

        job.status = TrainingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.celery_task_id = self.request.id or ""
        job.save(update_fields=["status", "started_at", "celery_task_id"])

        tmp = Path(tempfile.mkdtemp(prefix=f"stockpilot_train_{job_id}_"))
        try:
            data_yaml = _materialize_dataset(job.dataset, tmp)

            ultralytics = import_module("ultralytics")
            model = ultralytics.YOLO(job.base_model)
            results = model.train(
                data=str(data_yaml),
                epochs=job.epochs,
                batch=job.batch_size,
                imgsz=job.image_size,
                project=str(tmp),
                name="run",
                exist_ok=True,
                verbose=False,
            )

            # Persist best weights as a YoloModel for this tenant.
            best = Path(getattr(results, "save_dir", tmp / "run")) / "weights" / "best.pt"
            if not best.exists():
                raise RuntimeError(f"Training finished but {best} is missing")

            yolo_model = _register_model_from_weights(
                job=job,
                weights_path=best,
                metrics=_extract_metrics(results),
                class_names=_class_names_from_yaml(data_yaml),
            )
            job.output_model = yolo_model
            job.status = TrainingJob.Status.COMPLETED
            job.finished_at = timezone.now()
            job.logs = (job.logs + "\n[training completed]").strip()[-10_000:]
            job.save(
                update_fields=["output_model", "status", "finished_at", "logs"]
            )
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            job.error = (str(exc) + "\n" + tb)[-10_000:]
            job.status = TrainingJob.Status.FAILED
            job.finished_at = timezone.now()
            job.save(update_fields=["error", "status", "finished_at"])
            raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --- helpers ----------------------------------------------------------------


def _materialize_dataset(dataset: Dataset, root: Path) -> Path:
    """Write the dataset to a YOLO directory layout in `root` and return data.yaml."""
    images_train = root / "images" / "train"
    images_val = root / "images" / "val"
    labels_train = root / "labels" / "train"
    labels_val = root / "labels" / "val"
    for d in (images_train, images_val, labels_train, labels_val):
        d.mkdir(parents=True, exist_ok=True)

    # Collect distinct class names across all images, ordered.
    class_names: list[str] = []
    seen: set[str] = set()
    images = list(dataset.images.exclude(annotations=[]))
    for img in images:
        for ann in img.annotations:
            label = ann.get("label")
            if label and label not in seen:
                class_names.append(label)
                seen.add(label)
    if not class_names:
        raise ValueError("Dataset has no annotated images")

    # 80/20 train/val split.
    cutoff = max(1, int(len(images) * 0.8))
    train_imgs = images[:cutoff]
    val_imgs = images[cutoff:] or [train_imgs[-1]]

    for split, items in (("train", train_imgs), ("val", val_imgs)):
        img_dir = root / "images" / split
        lbl_dir = root / "labels" / split
        for img in items:
            src = Path(img.image.path)
            dst = img_dir / src.name
            shutil.copy2(src, dst)
            label_lines = []
            for ann in img.annotations:
                if ann.get("label") not in seen:
                    continue
                cls_idx = class_names.index(ann["label"])
                label_lines.append(
                    f"{cls_idx} {ann['x_center']:.6f} {ann['y_center']:.6f} "
                    f"{ann['width']:.6f} {ann['height']:.6f}"
                )
            (lbl_dir / (src.stem + ".txt")).write_text("\n".join(label_lines))

    data = {
        "path": str(root),
        "train": "images/train",
        "val": "images/val",
        "names": {i: name for i, name in enumerate(class_names)},
    }
    yaml_path = root / "data.yaml"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return yaml_path


def _class_names_from_yaml(data_yaml: Path) -> list[str]:
    data = yaml.safe_load(data_yaml.read_text())
    names = data.get("names", {})
    if isinstance(names, dict):
        return [names[k] for k in sorted(names.keys())]
    return list(names)


def _extract_metrics(results) -> dict:
    metrics = {}
    box = getattr(getattr(results, "results_dict", None), "get", None)
    if callable(box):
        for key in ("metrics/mAP50(B)", "metrics/mAP50-95(B)",
                    "metrics/precision(B)", "metrics/recall(B)"):
            val = box(key)
            if val is not None:
                metrics[key] = float(val)
    return metrics


def _register_model_from_weights(
    *, job: TrainingJob, weights_path: Path, metrics: dict, class_names: list[str]
) -> YoloModel:
    """Copy weights into MEDIA / save a YoloModel row pointing at it."""
    from django.conf import settings as dj_settings

    schema = job.dataset._meta.app_label  # any schema-aware connection attr would do
    # Actual schema directory comes from connection.schema_name at this point.
    from django.db import connection
    schema = connection.schema_name

    # Bump version per tenant
    next_version = (
        YoloModel.objects.aggregate_count if False else
        (YoloModel.objects.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    )

    target_dir = Path(dj_settings.MEDIA_ROOT) / "models" / schema
    target_dir.mkdir(parents=True, exist_ok=True)
    target_filename = f"job{job.pk}_v{next_version}.pt"
    target_path = target_dir / target_filename
    shutil.copy2(weights_path, target_path)

    # Build the relative path django expects in FileField.name
    relative = f"models/{schema}/{target_filename}"

    return YoloModel.objects.create(
        name=f"{job.dataset.name} v{next_version}",
        version=next_version,
        file=relative,
        source_job=job,
        is_active=False,
        metrics=metrics,
        class_names=class_names,
    )
