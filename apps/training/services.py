"""Public service API for the training app.

Used by views, admin, and tests. Wraps the Celery tasks so the rest of the
app never has to know about Celery directly.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Iterable

import yaml
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.utils import timezone

from .models import Dataset, TrainingImage, TrainingJob, YoloModel

logger = logging.getLogger(__name__)


# --- Dataset construction --------------------------------------------------


_VALID_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@transaction.atomic
def create_dataset_from_zip(
    zip_bytes: bytes, *, name: str, description: str = "", created_by=None
) -> Dataset:
    """Parse a YOLO-format ZIP (`images/`, `labels/`, optional `data.yaml`)
    and create a Dataset (status=draft) plus one TrainingImage per pair.

    Class indices in `.txt` labels are resolved to names via `data.yaml`
    if present, else falls back to "class_<idx>".
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = {m.filename: m for m in zf.infolist() if not m.is_dir()}

        class_names = _read_class_names(members, zf)
        image_names = sorted(
            n for n in members
            if "/images/" in n and Path(n).suffix.lower() in _VALID_IMAGE_SUFFIXES
        )
        if not image_names:
            raise ValueError("ZIP contains no images under an 'images/' folder")

        dataset = Dataset.objects.create(
            name=name,
            description=description,
            created_by=created_by,
        )

        for img_name in image_names:
            stem = Path(img_name).stem
            label_name = next(
                (
                    n for n in members
                    if "/labels/" in n and Path(n).stem == stem
                    and Path(n).suffix == ".txt"
                ),
                None,
            )
            if label_name is None:
                raise ValueError(f"Image {img_name!r} has no matching .txt label")

            img_bytes = zf.read(img_name)
            label_text = zf.read(label_name).decode("utf-8", errors="replace")
            annotations = _parse_yolo_label_file(label_text, class_names)

            ti = TrainingImage(
                dataset=dataset,
                annotations=annotations,
                suggestions_status=TrainingImage.SuggestionsStatus.DONE,
            )
            ti.image.save(Path(img_name).name, ContentFile(img_bytes), save=False)
            ti.save()

        return dataset


def _read_class_names(
    members: dict[str, zipfile.ZipInfo], zf: zipfile.ZipFile
) -> list[str] | None:
    """Return class names from data.yaml if present (and parseable)."""
    yaml_name = next((n for n in members if n.endswith("data.yaml")), None)
    if yaml_name is None:
        return None
    try:
        data = yaml.safe_load(zf.read(yaml_name).decode("utf-8"))
    except yaml.YAMLError:
        return None
    names = data.get("names") if isinstance(data, dict) else None
    if isinstance(names, dict):
        return [names[k] for k in sorted(names.keys())]
    if isinstance(names, list):
        return names
    return None


_LABEL_LINE = re.compile(
    r"^(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$"
)


def _parse_yolo_label_file(text: str, class_names: list[str] | None) -> list[dict]:
    annotations: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LABEL_LINE.match(line)
        if not m:
            raise ValueError(f"Malformed label line: {line!r}")
        cls_idx = int(m.group(1))
        if class_names and cls_idx < len(class_names):
            label = class_names[cls_idx]
        else:
            label = f"class_{cls_idx}"
        annotations.append(
            {
                "label": label,
                "x_center": float(m.group(2)),
                "y_center": float(m.group(3)),
                "width": float(m.group(4)),
                "height": float(m.group(5)),
            }
        )
    return annotations


# --- Image lifecycle -------------------------------------------------------


def add_image(
    dataset: Dataset,
    *,
    image_file,
    uploaded_by=None,
) -> TrainingImage:
    """Add a single image to a draft dataset; queue suggestion generation."""
    if dataset.status != Dataset.Status.DRAFT:
        raise ValueError("Cannot add images to a frozen dataset")

    ti = TrainingImage.objects.create(
        dataset=dataset,
        image=image_file,
        uploaded_by=uploaded_by,
    )

    # Queue async suggestion generation.
    from .tasks import generate_suggestions

    generate_suggestions.delay(ti.pk, connection.schema_name)
    return ti


def save_annotations(image: TrainingImage, annotations: Iterable[dict]) -> TrainingImage:
    cleaned: list[dict] = []
    for ann in annotations:
        cleaned.append(_validate_annotation(ann))
    image.annotations = cleaned
    image.save(update_fields=["annotations", "updated_at"])
    return image


def _validate_annotation(ann: dict) -> dict:
    """Coerce + validate a user-submitted annotation dict."""
    label = (ann.get("label") or "").strip()
    if not label:
        raise ValueError("Each annotation must carry a non-empty label")
    out = {"label": label}
    for key in ("x_center", "y_center", "width", "height"):
        val = float(ann[key])
        if not 0.0 <= val <= 1.0:
            raise ValueError(f"{key} must be in [0, 1]; got {val}")
        out[key] = val
    if out["width"] <= 0 or out["height"] <= 0:
        raise ValueError("width and height must be > 0")
    return out


# --- Dataset freeze --------------------------------------------------------


@transaction.atomic
def freeze_dataset(dataset: Dataset) -> Dataset:
    if dataset.status == Dataset.Status.FROZEN:
        return dataset
    dataset.status = Dataset.Status.FROZEN
    dataset.frozen_at = timezone.now()
    dataset.save(update_fields=["status", "frozen_at", "updated_at"])
    return dataset


# --- Training job ----------------------------------------------------------


def start_training_job(
    dataset: Dataset,
    *,
    epochs: int = 50,
    batch_size: int = 4,
    image_size: int = 640,
    base_model: str = "yolo11n.pt",
    created_by=None,
) -> TrainingJob:
    """Freeze the dataset (if needed) and queue a training run."""
    if not dataset.images.exclude(annotations=[]).exists():
        raise ValueError("Dataset has no annotated images — train would be empty")
    freeze_dataset(dataset)

    job = TrainingJob.objects.create(
        dataset=dataset,
        epochs=epochs,
        batch_size=batch_size,
        image_size=image_size,
        base_model=base_model,
        created_by=created_by,
    )

    from .tasks import train_yolo

    train_yolo.delay(job.pk, connection.schema_name)
    return job


# --- Model activation ------------------------------------------------------


def activate_model(yolo_model: YoloModel) -> YoloModel:
    """Make this model the tenant's active one (atomic single-row toggle)."""
    yolo_model.activate()
    return yolo_model
