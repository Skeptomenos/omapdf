"""Redaction tests (preview-parity spec §6.3 items 11–15)."""

import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest

from omapreview import engine
from omapreview.ops import OpError
from tests.data.make_docs import make_image_asset, make_image_only_page_pdf, make_secret_pdf


def _pdftotext(path: Path) -> str:
    if not shutil.which("pdftotext"):
        return ""
    proc = subprocess.run(
        ["pdftotext", str(path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


@pytest.fixture()
def secret_pdf(tmp_path):
    return make_secret_pdf(tmp_path / "secret.pdf")


@pytest.fixture()
def image_pdf(tmp_path):
    img = make_image_asset(tmp_path / "chip.png")
    return make_image_only_page_pdf(tmp_path / "image.pdf", img)


def test_match_redact_removes_text(secret_pdf, tmp_path):
    """11. match on SECRET → get_text/pdftotext have no SECRET."""
    out = tmp_path / "redacted.pdf"
    result = engine.apply(
        secret_pdf,
        [{"op": "redact", "page": 1, "match": "SECRET"}],
        output=out,
    )
    assert result["applied"][0]["verify"] == {"text_still_present": False}
    text = pymupdf.open(out)[0].get_text()
    assert "SECRET" not in text
    assert "Public" in text
    if shutil.which("pdftotext"):
        assert "SECRET" not in _pdftotext(out)


def test_rect_redact_on_image_pixels(image_pdf, tmp_path):
    """12. Rect over embedded image → sampling is near-black."""
    out = tmp_path / "redacted.pdf"
    doc = pymupdf.open(image_pdf)
    page = doc[0]
    rect = [0, 0, page.rect.width, page.rect.height]
    doc.close()
    engine.apply(
        image_pdf,
        [{"op": "redact", "page": 1, "rect": rect}],
        output=out,
    )
    page = pymupdf.open(out)[0]
    pix = page.get_pixmap(clip=pymupdf.Rect(rect))
    cx, cy = pix.width // 2, pix.height // 2
    r, g, b = pix.pixel(cx, cy)
    assert r < 16 and g < 16 and b < 16


def test_ink_overlay_leaves_text(secret_pdf, tmp_path):
    """13. Black ink overlay is not redact — text still extractable."""
    out = tmp_path / "ink.pdf"
    doc = pymupdf.open(secret_pdf)
    page = doc[0]
    rects = page.search_for("SECRET")
    doc.close()
    r = rects[0]
    strokes = [
        [
            [r.x0, r.y0],
            [r.x1, r.y0],
            [r.x1, r.y1],
            [r.x0, r.y1],
            [r.x0, r.y0],
        ]
    ]
    engine.apply(
        secret_pdf,
        [{"op": "ink", "page": 1, "strokes": strokes, "color": [0, 0, 0], "width": 4}],
        output=out,
    )
    assert "SECRET" in pymupdf.open(out)[0].get_text()


def test_dry_run_redact_writes_nothing(secret_pdf, tmp_path):
    """14. Dry-run redact does not write removal."""
    out = tmp_path / "out.pdf"
    result = engine.apply(
        secret_pdf,
        [{"op": "redact", "page": 1, "match": "SECRET"}],
        output=out,
        dry_run=True,
    )
    assert result["output"] is None
    assert result["applied"][0]["applied"] is False
    assert "SECRET" in pymupdf.open(secret_pdf)[0].get_text()


def test_verify_failure_aborts_batch(secret_pdf, tmp_path, monkeypatch):
    """15. Verify hook fails the save if extraction still finds the string."""
    out = tmp_path / "out.pdf"

    def fail_verify(_page, _match, _rects):
        return {"text_still_present": True}

    monkeypatch.setattr(engine, "_verify_redact", fail_verify)
    with pytest.raises(OpError, match="verify failed"):
        engine.apply(
            secret_pdf,
            [{"op": "redact", "page": 1, "match": "SECRET"}],
            output=out,
        )
    assert not out.exists()
