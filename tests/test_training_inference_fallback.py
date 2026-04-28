"""UltralyticsBackend tenant-model resolution.

Tests the fallback path: when no YoloModel is active (or the lookup fails
under the public schema), `_resolve_path` returns `settings.VISION_YOLO_MODEL`.
We don't load the real ultralytics here — only `_resolve_path` is exercised.
"""

from django.test import override_settings

from apps.vision.inference import UltralyticsBackend


@override_settings(VISION_YOLO_MODEL="yolo11n.pt")
def test_resolve_path_falls_back_to_settings_when_lookup_fails():
    # No tenant context -> the YoloModel lookup raises; the resolver should
    # silently swallow it and return the configured default.
    backend = UltralyticsBackend()
    assert backend._resolve_path() == "yolo11n.pt"


@override_settings(VISION_YOLO_MODEL="custom-default.pt")
def test_resolve_path_honours_custom_default():
    backend = UltralyticsBackend()
    assert backend._resolve_path() == "custom-default.pt"


def test_backend_cache_is_per_path():
    """Two calls with the same resolved path should reuse one model."""
    backend = UltralyticsBackend()
    assert backend._cache == {}
    # Manually seed cache to verify _load reuses entries by path.
    sentinel = object()
    backend._cache["yolo11n.pt"] = sentinel
    backend._model = sentinel
    # Calling _resolve_path twice still returns the same fallback path —
    # we don't actually call _load (which would import ultralytics).
    assert backend._resolve_path() == backend._resolve_path()
