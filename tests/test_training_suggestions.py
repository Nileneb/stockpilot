"""Pure-logic tests for the suggestions module.

No DB, no ML — just IoU math and merge dedup. These run fast and are safe
to execute in any environment.
"""

from apps.training.suggestions import Suggestion, _iou, merge


def _box(label: str | None, source: str, x: float, y: float, w: float, h: float, conf: float = 0.9) -> Suggestion:
    return Suggestion(
        label=label,
        confidence=conf,
        source=source,
        x_center=x,
        y_center=y,
        width=w,
        height=h,
    )


def test_iou_identical_boxes_is_one():
    a = _box("bottle", "yolo", 0.5, 0.5, 0.2, 0.2)
    assert abs(_iou(a, a) - 1.0) < 1e-9


def test_iou_disjoint_boxes_is_zero():
    a = _box("bottle", "yolo", 0.2, 0.2, 0.1, 0.1)
    b = _box(None, "sam", 0.8, 0.8, 0.1, 0.1)
    assert _iou(a, b) == 0.0


def test_iou_partial_overlap_known_value():
    # 0.4-wide square at (0.3, 0.3) and 0.4-wide square at (0.5, 0.5)
    # -> overlap is 0.2x0.2=0.04, union = 0.16 + 0.16 - 0.04 = 0.28
    a = _box("a", "yolo", 0.3, 0.3, 0.4, 0.4)
    b = _box(None, "sam", 0.5, 0.5, 0.4, 0.4)
    assert abs(_iou(a, b) - (0.04 / 0.28)) < 1e-9


def test_merge_drops_sam_box_overlapping_yolo():
    yolo = [_box("bottle", "yolo", 0.5, 0.5, 0.2, 0.2)]
    sam = [_box(None, "sam", 0.5, 0.5, 0.2, 0.2)]  # identical, IoU=1
    out = merge(yolo, sam, iou_threshold=0.5)
    assert len(out) == 1
    assert out[0].source == "yolo"


def test_merge_keeps_sam_box_when_disjoint():
    yolo = [_box("bottle", "yolo", 0.2, 0.2, 0.1, 0.1)]
    sam = [_box(None, "sam", 0.8, 0.8, 0.1, 0.1)]
    out = merge(yolo, sam, iou_threshold=0.5)
    assert len(out) == 2
    sources = {s.source for s in out}
    assert sources == {"yolo", "sam"}


def test_merge_threshold_boundary():
    # IoU just below 0.5 -> SAM box kept.
    yolo = [_box("a", "yolo", 0.3, 0.3, 0.4, 0.4)]
    sam = [_box(None, "sam", 0.5, 0.5, 0.4, 0.4)]  # IoU ≈ 0.143
    assert len(merge(yolo, sam, iou_threshold=0.5)) == 2
    # And with a very low threshold it gets dropped.
    assert len(merge(yolo, sam, iou_threshold=0.1)) == 1


def test_suggestion_to_json_rounds_floats():
    s = _box("bottle", "yolo", 0.123456, 0.234567, 0.345678, 0.456789, conf=0.987654)
    payload = s.to_json()
    assert payload["label"] == "bottle"
    assert payload["source"] == "yolo"
    assert payload["confidence"] == 0.9877
    assert payload["x_center"] == 0.1235
    assert payload["y_center"] == 0.2346
    assert payload["width"] == 0.3457
    assert payload["height"] == 0.4568
