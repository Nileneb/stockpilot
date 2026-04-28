"""Pure-logic tests for the YOLO ZIP parser internals (no DB)."""

import io
import zipfile

import pytest

from apps.training.services import (
    _parse_yolo_label_file,
    _read_class_names,
)


def _zip_with(files: dict[str, bytes]) -> tuple[dict, zipfile.ZipFile]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    zf = zipfile.ZipFile(buf)
    members = {m.filename: m for m in zf.infolist() if not m.is_dir()}
    return members, zf


def test_parse_label_file_uses_class_names():
    text = "0 0.5 0.5 0.4 0.4\n1 0.1 0.1 0.05 0.05\n"
    out = _parse_yolo_label_file(text, ["bottle", "can"])
    assert out == [
        {"label": "bottle", "x_center": 0.5, "y_center": 0.5, "width": 0.4, "height": 0.4},
        {"label": "can", "x_center": 0.1, "y_center": 0.1, "width": 0.05, "height": 0.05},
    ]


def test_parse_label_file_falls_back_when_no_names():
    out = _parse_yolo_label_file("3 0.5 0.5 0.1 0.1\n", None)
    assert out == [
        {"label": "class_3", "x_center": 0.5, "y_center": 0.5, "width": 0.1, "height": 0.1}
    ]


def test_parse_label_file_skips_blank_lines():
    text = "\n  \n0 0.5 0.5 0.1 0.1\n\n"
    out = _parse_yolo_label_file(text, ["x"])
    assert len(out) == 1


def test_parse_label_file_rejects_malformed_lines():
    with pytest.raises(ValueError, match="Malformed"):
        _parse_yolo_label_file("not a label line\n", None)


def test_read_class_names_dict_form():
    members, zf = _zip_with(
        {"data.yaml": b"names:\n  0: bottle\n  1: can\n"}
    )
    assert _read_class_names(members, zf) == ["bottle", "can"]


def test_read_class_names_list_form():
    members, zf = _zip_with(
        {"data.yaml": b"names: [bottle, can, box]\n"}
    )
    assert _read_class_names(members, zf) == ["bottle", "can", "box"]


def test_read_class_names_missing_returns_none():
    members, zf = _zip_with({"images/foo.png": b"\x89PNG"})
    assert _read_class_names(members, zf) is None


def test_read_class_names_invalid_yaml_returns_none():
    members, zf = _zip_with({"data.yaml": b": invalid : yaml :\n"})
    assert _read_class_names(members, zf) is None
