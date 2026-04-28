"""Auto-suggestion of bounding boxes for training images.

Two backends run in sequence:

1. **YOLO11x** (the larger COCO-trained sibling of the inference default).
   Produces labeled boxes for the 80 COCO classes. Good first-pass for
   common shelf items (bottle, cup, bowl, book, scissors, etc.).
2. **SAM 2** (segment-anything tiny). Produces label-less boxes for every
   recognizable object — catches custom items YOLO doesn't know.

Results are deduplicated: a SAM box that overlaps an existing YOLO box by
≥ IoU 0.5 is dropped (YOLO carries the label, SAM doesn't).

Only the merged list is persisted to `TrainingImage.auto_suggestions`. The
user then accepts/edits/deletes them in the browser annotator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Suggestion:
    label: str | None
    confidence: float
    source: str  # "yolo" | "sam"
    x_center: float
    y_center: float
    width: float
    height: float

    def to_json(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "x_center": round(self.x_center, 4),
            "y_center": round(self.y_center, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
        }


def _iou(a: Suggestion, b: Suggestion) -> float:
    """Intersection-over-Union for two normalized centre-form boxes."""
    ax1, ay1 = a.x_center - a.width / 2, a.y_center - a.height / 2
    ax2, ay2 = a.x_center + a.width / 2, a.y_center + a.height / 2
    bx1, by1 = b.x_center - b.width / 2, b.y_center - b.height / 2
    bx2, by2 = b.x_center + b.width / 2, b.y_center + b.height / 2

    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    union = (a.width * a.height) + (b.width * b.height) - inter
    return inter / union if union > 0 else 0.0


def merge(
    yolo: list[Suggestion],
    sam: list[Suggestion],
    iou_threshold: float = 0.5,
) -> list[Suggestion]:
    """Drop SAM boxes that overlap an existing YOLO box."""
    merged: list[Suggestion] = list(yolo)
    for s in sam:
        if any(_iou(s, y) >= iou_threshold for y in yolo):
            continue
        merged.append(s)
    return merged


def run_yolo(image_path: str) -> list[Suggestion]:
    ultralytics = import_module("ultralytics")
    model = ultralytics.YOLO(getattr(settings, "TRAINING_SUGGEST_YOLO_MODEL", "yolo11x.pt"))
    results = model(image_path, verbose=False)
    out: list[Suggestion] = []
    for r in results:
        if r.boxes is None:
            continue
        for box, cls_idx, conf in zip(
            r.boxes.xywhn.tolist(),
            r.boxes.cls.tolist(),
            r.boxes.conf.tolist(),
        ):
            x, y, w, h = box
            out.append(
                Suggestion(
                    label=r.names[int(cls_idx)],
                    confidence=float(conf),
                    source="yolo",
                    x_center=float(x),
                    y_center=float(y),
                    width=float(w),
                    height=float(h),
                )
            )
    return out


def run_sam(image_path: str, *, min_area: float = 0.001) -> list[Suggestion]:
    """SAM 2 segment-everything in 'auto' mode → bboxes from masks.

    `min_area` filters out noisy tiny masks (normalized to image area).
    """
    ultralytics = import_module("ultralytics")
    sam_cls = getattr(ultralytics, "SAM", None)
    if sam_cls is None:
        raise RuntimeError(
            "ultralytics.SAM not available — upgrade ultralytics to a version "
            "that ships SAM 2 (>= 8.3)."
        )
    model = sam_cls(getattr(settings, "TRAINING_SUGGEST_SAM_MODEL", "sam2_t.pt"))
    results = model(image_path, verbose=False)

    out: list[Suggestion] = []
    for r in results:
        masks = getattr(r, "masks", None)
        if masks is None or masks.xyn is None:
            continue
        # masks.xyn is per-mask polygon points in normalized coords;
        # convert each polygon's bounding box.
        h_img, w_img = r.orig_shape if r.orig_shape else (1, 1)
        for poly in masks.xyn:
            # poly is shape (N, 2) — normalized x, y points
            try:
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
            except Exception:  # noqa: BLE001
                continue
            if not xs or not ys:
                continue
            x1, x2 = max(0.0, min(xs)), min(1.0, max(xs))
            y1, y2 = max(0.0, min(ys)), min(1.0, max(ys))
            w, h = x2 - x1, y2 - y1
            if w * h < min_area:
                continue
            out.append(
                Suggestion(
                    label=None,
                    confidence=0.0,  # SAM doesn't expose per-mask scores in auto mode
                    source="sam",
                    x_center=x1 + w / 2,
                    y_center=y1 + h / 2,
                    width=w,
                    height=h,
                )
            )
    return out


def generate_for_image_path(image_path: str, *, use_sam: bool | None = None) -> list[Suggestion]:
    """Run YOLO11x and (optionally) SAM 2 on an image, return merged suggestions."""
    if use_sam is None:
        use_sam = getattr(settings, "TRAINING_SUGGEST_USE_SAM", True)

    yolo_suggestions = run_yolo(image_path)
    sam_suggestions: list[Suggestion] = []
    if use_sam:
        try:
            sam_suggestions = run_sam(image_path)
        except Exception as exc:  # noqa: BLE001 — SAM is optional, never block YOLO
            logger.warning("SAM suggestion run failed: %s", exc)
    return merge(yolo_suggestions, sam_suggestions)
