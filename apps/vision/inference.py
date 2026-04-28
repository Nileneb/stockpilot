"""Inference backends.

`UltralyticsBackend` is the production default — runs a real YOLO model via
the `ultralytics` package. Imports are deferred so the module loads even if
the dep isn't installed (tests can then point at `StubBackend`).

`StubBackend` exists ONLY for tests and CI: deterministic fake detections
keyed off the image bytes. Never use it in production.

Active backend is selected via `settings.VISION_INFERENCE_BACKEND` (dotted
path). Default in `base.py` is the Ultralytics backend.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Iterable, Protocol

from django.conf import settings


@dataclass(frozen=True)
class DetectionResult:
    label: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None  # (x, y, w, h) normalized


class InferenceBackend(Protocol):
    def detect(self, image_path: str) -> list[DetectionResult]: ...


class StubBackend:
    """Deterministic fake backend for tests and ML-less environments.

    Uses a hash of the file bytes to choose a label set so the same image
    always returns the same detections.
    """

    LABEL_SETS = (
        ("bottle", 4),
        ("can", 6),
        ("box", 3),
        ("pack", 2),
    )

    def detect(self, image_path: str) -> list[DetectionResult]:
        path = Path(image_path)
        digest = hashlib.sha1(path.read_bytes()).digest()
        idx = digest[0] % len(self.LABEL_SETS)
        label, count = self.LABEL_SETS[idx]
        confidence = 0.7 + (digest[1] % 30) / 100.0
        return [
            DetectionResult(label=label, confidence=round(confidence, 4))
            for _ in range(count)
        ]


class UltralyticsBackend:
    """Real YOLO inference. Imports ultralytics lazily.

    Configure via settings:
        VISION_YOLO_MODEL = "yolo11n.pt"  # or yolo26n.pt etc.
        VISION_YOLO_CONFIDENCE = 0.25
    """

    def __init__(self):
        self._model = None

    def _load(self):
        if self._model is None:
            ultralytics = import_module("ultralytics")
            model_name = getattr(settings, "VISION_YOLO_MODEL", "yolo11n.pt")
            self._model = ultralytics.YOLO(model_name)
        return self._model

    def detect(self, image_path: str) -> list[DetectionResult]:
        model = self._load()
        conf = float(getattr(settings, "VISION_YOLO_CONFIDENCE", 0.25))
        results = model(image_path, conf=conf, verbose=False)
        out: list[DetectionResult] = []
        for result in results:
            names = result.names
            if result.boxes is None:
                continue
            for box, cls_idx, score in zip(
                result.boxes.xywhn.tolist(),
                result.boxes.cls.tolist(),
                result.boxes.conf.tolist(),
            ):
                x, y, w, h = box
                out.append(
                    DetectionResult(
                        label=names[int(cls_idx)],
                        confidence=round(float(score), 4),
                        bbox=(x, y, w, h),
                    )
                )
        return out


def get_backend() -> InferenceBackend:
    dotted = getattr(
        settings,
        "VISION_INFERENCE_BACKEND",
        "apps.vision.inference.UltralyticsBackend",
    )
    module_path, _, cls_name = dotted.rpartition(".")
    module = import_module(module_path)
    return getattr(module, cls_name)()


def aggregate_by_label(detections: Iterable[DetectionResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for det in detections:
        counts[det.label] = counts.get(det.label, 0) + 1
    return counts
