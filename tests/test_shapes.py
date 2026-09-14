"""Shape annotation ops: line, arrow, rect, oval."""

import pymupdf
import pytest

from omapdf import engine, read
from omapdf.ops import OpError, validate


@pytest.fixture()
def blank_page(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _annots(path):
    return read.extract(path)["pages"][0]["annotations"]


def test_shape_line(blank_page, tmp_path):
    out = tmp_path / "line.pdf"
    result = engine.apply(
        blank_page,
        [{
            "op": "shape",
            "page": 1,
            "shape": "line",
            "from": [72, 100],
            "to": [300, 200],
            "color": [0.1, 0.1, 0.1],
            "width": 2,
        }],
        output=out,
    )
    assert result["applied"][0]["shape"] == "line"
    annots = _annots(out)
    assert len(annots) == 1
    assert annots[0]["type"] == "Line"


def test_shape_arrow(blank_page, tmp_path):
    out = tmp_path / "arrow.pdf"
    engine.apply(
        blank_page,
        [{
            "op": "shape",
            "page": 1,
            "shape": "arrow",
            "from": [50, 50],
            "to": [250, 150],
        }],
        output=out,
    )
    annots = _annots(out)
    assert len(annots) == 1
    assert annots[0]["type"] == "Line"


def test_shape_rect_and_oval(blank_page, tmp_path):
    out = tmp_path / "shapes.pdf"
    engine.apply(
        blank_page,
        [
            {
                "op": "shape",
                "page": 1,
                "shape": "rect",
                "rect": [80, 80, 200, 160],
            },
            {
                "op": "shape",
                "page": 1,
                "shape": "oval",
                "rect": [220, 80, 340, 200],
            },
        ],
        output=out,
    )
    types = {a["type"] for a in _annots(out)}
    assert types == {"Square", "Circle"}


def test_shape_validation():
    with pytest.raises(OpError, match="shape"):
        validate({"op": "shape", "page": 1, "shape": "line"})
    with pytest.raises(OpError, match="rect"):
        validate({"op": "shape", "page": 1, "shape": "rect"})
    with pytest.raises(OpError, match="unknown shape"):
        validate({
            "op": "shape",
            "page": 1,
            "shape": "triangle",
            "rect": [0, 0, 10, 10],
        })


def test_shape_dry_run(blank_page):
    result = engine.apply(
        blank_page,
        [{
            "op": "shape",
            "page": 1,
            "shape": "rect",
            "rect": [10, 10, 100, 100],
        }],
        dry_run=True,
    )
    assert result["output"] is None
    assert result["applied"][0]["applied"] is False
    rect = result["applied"][0]["rect"]
    assert rect[0] <= 10 and rect[1] <= 10 and rect[2] >= 100 and rect[3] >= 100
