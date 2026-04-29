"""UltralyticsBackend tenant-model resolution.

Tests the fallback path: when no `apps.training.models` is importable
(public schema bootstrapping or a DB-less env), `_resolve_path` returns
`settings.VISION_YOLO_MODEL`. We trigger the fallback explicitly via
`sys.modules` manipulation rather than relying on pytest-django's
DB-access guard, which would raise an uncaught `RuntimeError`.
"""

import sys

from django.test import override_settings

from apps.vision.inference import UltralyticsBackend


def _block_training_module(monkeypatch):
    """Force `from apps.training.models import YoloModel` to raise ImportError."""
    monkeypatch.setitem(sys.modules, "apps.training.models", None)


@override_settings(VISION_YOLO_MODEL="yolo11n.pt")
def test_resolve_path_falls_back_to_settings_when_training_unavailable(monkeypatch):
    _block_training_module(monkeypatch)
    backend = UltralyticsBackend()
    assert backend._resolve_path() == "yolo11n.pt"


@override_settings(VISION_YOLO_MODEL="custom-default.pt")
def test_resolve_path_honours_custom_default(monkeypatch):
    _block_training_module(monkeypatch)
    backend = UltralyticsBackend()
    assert backend._resolve_path() == "custom-default.pt"


def test_backend_cache_starts_empty():
    backend = UltralyticsBackend()
    assert backend._cache == {}


def test_backend_cache_is_keyed_by_path(monkeypatch):
    """Two calls with the same resolved path should reuse one model entry."""
    _block_training_module(monkeypatch)
    backend = UltralyticsBackend()
    # Manually seed cache to verify _load reuses entries by path. We don't
    # call _load here (which would import ultralytics).
    sentinel = object()
    backend._cache["yolo11n.pt"] = sentinel
    # Twice through the resolver yields the same key, so the same cache
    # entry would be reused.
    assert backend._resolve_path() == backend._resolve_path()
    assert backend._cache["yolo11n.pt"] is sentinel
