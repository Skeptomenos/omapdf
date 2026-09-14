"""crop_pages op — CropBox surgery and markup coordinate regression."""

import pymupdf
import pytest

from omapreview import engine, read
from omapreview.crop_coords import transform_pending_for_crop
from omapreview.ops import OpError
from tests.data.make_docs import make_labeled_pdf


@pytest.fixture()
def letter_page(tmp_path):
    path = tmp_path / "letter.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "CROP ME", fontsize=20)
    doc.save(str(path))
    doc.close()
    return path


def test_crop_pages_sets_cropbox(letter_page, tmp_path):
    out = tmp_path / "cropped.pdf"
    result = engine.apply(
        letter_page,
        [{"op": "crop_pages", "pages": [1], "rect": [50, 50, 400, 300]}],
        output=out,
    )
    assert result["applied"][0]["resolved"][0]["size_after"] == [350.0, 250.0]
    doc = pymupdf.open(out)
    page = doc[0]
    assert abs(page.rect.width - 350) < 0.1
    assert abs(page.rect.height - 250) < 0.1
    doc.close()


def test_highlight_coords_after_crop(letter_page, tmp_path):
    mid = tmp_path / "marked.pdf"
    engine.apply(
        letter_page,
        [{"op": "highlight", "page": 1, "rect": [70, 90, 180, 120]}],
        output=mid,
    )
    out = tmp_path / "cropped.pdf"
    engine.apply(
        mid,
        [{"op": "crop_pages", "pages": [1], "rect": [50, 50, 400, 300]}],
        output=out,
    )
    annots = read.extract(out)["pages"][0]["annotations"]
    assert annots
    rect = annots[0]["rect"]
    assert rect[0] < 40 and rect[1] < 40


def test_shape_after_crop_uses_cropped_space(letter_page, tmp_path):
    cropped = tmp_path / "cropped.pdf"
    engine.apply(
        letter_page,
        [{"op": "crop_pages", "pages": [1], "rect": [50, 50, 400, 300]}],
        output=cropped,
    )
    out = tmp_path / "shaped.pdf"
    engine.apply(
        cropped,
        [{
            "op": "shape",
            "page": 1,
            "shape": "rect",
            "rect": [20, 20, 120, 80],
        }],
        output=out,
    )
    annots = read.extract(out)["pages"][0]["annotations"]
    assert len(annots) == 1
    assert annots[0]["type"] == "Square"
    assert annots[0]["rect"][0] < 30


def test_transform_pending_for_crop():
    pending = [
        {"kind": "highlight", "page": 0, "x0": 70, "y0": 90, "x1": 180, "y1": 120},
        {"kind": "text", "page": 0, "x": 80, "y": 100, "text": "x", "size": 12},
        {"kind": "shape", "page": 1, "shape": "line", "x0": 0, "y0": 0, "x1": 10, "y1": 10,
         "color": [0, 0, 0], "width": 2},
    ]
    transform_pending_for_crop(pending, 0, [50, 50, 400, 300])
    assert pending[0]["x0"] == 20
    assert pending[0]["y0"] == 40
    assert pending[1]["x"] == 30
    assert pending[2]["x0"] == 0


def test_crop_validation():
    with pytest.raises(OpError, match="positive width"):
        from omapreview.ops import validate

        validate({"op": "crop_pages", "pages": [1], "rect": [10, 10, 10, 50]})
