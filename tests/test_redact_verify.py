"""Word-snap redact verify: glyph coverage, not get_textbox clip.

Synthetic dense statement only. No bank/medical/PII strings.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from omepreview import engine, redact_scope
from omepreview.ops import OpError

KEEP = "KEEP_VISIBLE"
SECRET = "SECRET99"
IBAN = "DE00SYNTHETIC00000000001"
STICKY = "STICKY_SYNTH"
FREETEXT = "NOTE_SYNTH"
LABEL = "LABEL"


def _make_dense_statement(path: Path) -> Path:
    """Times-like rows: short labels, synthetic IBANs, dates, overlapping boxes."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 56), "SYNTHETIC STATEMENT REF 0000", fontsize=11, fontname="tiro")
    y = 88
    for i in range(10):
        page.insert_text(
            (40, y),
            f"2026-01-{i + 10:02d} TXN{i:04d} DE00SYNTHETIC{i:011d} {100 + i}.99 {LABEL}",
            fontsize=9,
            fontname="tiro",
        )
        y += 10
    page.add_text_annot(pymupdf.Point(520, 70), STICKY)
    page.add_freetext_annot(pymupdf.Rect(40, 280, 200, 310), FREETEXT, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def _word_snap_ops(page: pymupdf.Page, band: pymupdf.Rect) -> list[dict]:
    ops = []
    for word in page.get_text("words"):
        rect = pymupdf.Rect(word[:4])
        if rect.intersects(band):
            ops.append(
                {
                    "op": "redact",
                    "page": 1,
                    "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                    "fill": [0, 0, 0],
                }
            )
    return ops


def test_word_snap_graze_does_not_fail_on_next_line(tmp_path):
    """Tight Times word box + 2pt graze: get_textbox still sees KEEP, glyphs do not."""
    src = tmp_path / "graze.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), SECRET, fontsize=12, fontname="tiro")
    page.insert_text((50, 118), KEEP, fontsize=12, fontname="tiro")
    doc.save(str(src))
    doc.close()

    src_doc = pymupdf.open(src)
    try:
        secret = src_doc[0].search_for(SECRET)[0]
        clip = pymupdf.Rect(secret)
        clip.y1 += 2.0
        # get_textbox(clip) reports the next line even though KEEP's bbox is
        # only grazed — the old verify treated that as leftover.
        assert "KEEP" in src_doc[0].get_textbox(clip)
    finally:
        src_doc.close()

    out = tmp_path / "out.pdf"
    result = engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": list(clip), "fill": [0, 0, 0]}],
        output=out,
    )
    assert result["applied"][0]["verify"]["text_still_present"] is False
    text = pymupdf.open(out)[0].get_text()
    assert SECRET not in text
    assert KEEP in text


def test_dense_word_snaps_save_with_notes(tmp_path):
    src = _make_dense_statement(tmp_path / "stmt.pdf")
    doc = pymupdf.open(src)
    page = doc[0]
    band = pymupdf.Rect(35, 70, 400, 175)
    ops = _word_snap_ops(page, band)
    doc.close()
    assert len(ops) >= 15

    out = tmp_path / "out.pdf"
    result = engine.apply(src, ops, output=out)
    assert all(item["verify"]["text_still_present"] is False for item in result["applied"])

    reopened = pymupdf.open(out)
    try:
        text = reopened[0].get_text()
        assert "DE00SYNTHETIC00000000000" not in text
        assert "2026-01-10" not in text
        assert LABEL in text or "SYNTHETIC STATEMENT" in text
        contents = [a.info.get("content", "") for a in (reopened[0].annots() or [])]
        assert STICKY in contents
        assert FREETEXT in contents or FREETEXT in text
    finally:
        reopened.close()


def test_verify_names_remnant_when_apply_skips_text(tmp_path, monkeypatch):
    src = tmp_path / "remain.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), SECRET, fontsize=12, fontname="tiro")
    page.insert_text((50, 400), KEEP, fontsize=12, fontname="tiro")
    doc.save(str(src))
    doc.close()
    rect = list(pymupdf.open(src)[0].search_for(SECRET)[0])

    monkeypatch.setattr(pymupdf.Page, "apply_redactions", lambda self, **_k: True)
    with pytest.raises(OpError, match=SECRET) as caught:
        engine.apply(
            src,
            [{"op": "redact", "page": 1, "rect": rect, "fill": [0, 0, 0]}],
            output=tmp_path / "out.pdf",
        )
    assert "leftover" in str(caught.value)
    assert "still extractable" in str(caught.value)


def test_match_still_fails_closed(tmp_path, monkeypatch):
    src = tmp_path / "match.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), SECRET, fontsize=12)
    doc.save(str(src))
    doc.close()
    monkeypatch.setattr(pymupdf.Page, "apply_redactions", lambda self, **_k: True)
    with pytest.raises(OpError, match=rf"match '{SECRET}' still extractable"):
        engine.apply(
            src,
            [{"op": "redact", "page": 1, "match": SECRET}],
            output=tmp_path / "out.pdf",
        )


def test_stamp_still_refuses(tmp_path):
    src = tmp_path / "stamp.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), SECRET, fontsize=12)
    page.add_stamp_annot(pymupdf.Rect(50, 80, 140, 120), stamp=0)
    doc.save(str(src))
    doc.close()
    rect = list(pymupdf.open(src)[0].search_for(SECRET)[0])
    with pytest.raises(OpError, match="Stamp"):
        engine.apply(
            src,
            [{"op": "redact", "page": 1, "rect": rect}],
            output=tmp_path / "out.pdf",
        )


def test_graze_neighbor_is_not_a_remnant():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), SECRET, fontsize=12, fontname="tiro")
    page.insert_text((50, 118), KEEP, fontsize=12, fontname="tiro")
    secret = page.search_for(SECRET)[0]
    clip = pymupdf.Rect(secret)
    clip.y1 += 2.0
    page.add_redact_annot(secret, fill=(0, 0, 0))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
    assert "KEEP" in page.get_textbox(clip)
    assert redact_scope.leftover_text_detail(page, None, [clip]) is None
    assert KEEP in page.get_text()
    assert SECRET not in page.get_text()
    doc.close()
