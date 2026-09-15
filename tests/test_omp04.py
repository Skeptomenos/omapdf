"""OMP-04 — region redact strips in-rect payloads and fails closed.

Generated PDFs only. Synthetic tokens, no bank/medical/PII.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from omepreview import engine, read
from omepreview.ops import OpError
from tests.data.make_docs import make_unique_secret_pdf

PAGE_SECRET = "PAGE_SECRET"
NOTE_SECRET = "NOTE_SECRET"
NOTE_OUTSIDE = "NOTE_OUTSIDE"
KEEP = "KEEP-VISIBLE"
FIELD_SECRET = "FIELD_SECRET"
FREETEXT_SECRET = "FREETEXT_SECRET"
ATTACH_SECRET = b"ATTACH_SECRET_BYTES"
REPLY_SECRET = "REPLY_SECRET"

# Covers PAGE_SECRET at (50,100) and a note icon at (50,70); KEEP sits at y=400.
REGION = [40, 40, 300, 150]


def _xref_has(path: Path, token: str | bytes) -> bool:
    needle = token.encode("utf-8") if isinstance(token, str) else token
    doc = pymupdf.open(path)
    try:
        for i in range(1, doc.xref_length()):
            try:
                obj = (doc.xref_object(i) or "").encode("latin1", "replace")
            except Exception:
                obj = b""
            try:
                stream = doc.xref_stream(i) or b""
            except Exception:
                stream = b""
            if needle in obj or needle in stream:
                return True
        return False
    finally:
        doc.close()


def _make_region_pdf(
    path: Path,
    *,
    note_inside: bool = True,
    note_outside: bool = True,
    page_secret: bool = True,
) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    if page_secret:
        page.insert_text((50, 100), PAGE_SECRET, fontsize=12)
    page.insert_text((50, 400), KEEP, fontsize=12)
    if note_inside:
        page.add_text_annot(pymupdf.Point(50, 70), NOTE_SECRET)
    if note_outside:
        page.add_text_annot(pymupdf.Point(50, 400), NOTE_OUTSIDE)
    doc.save(str(path))
    doc.close()
    return path


def test_note_in_region_gone_after_save_outside_remains(tmp_path):
    src = _make_region_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    result = engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
        output=out,
    )
    assert result["applied"][0]["verify"]["text_still_present"] is False
    assert result["applied"][0]["verify"]["payloads_still_present"] == []

    reopened = pymupdf.open(out)
    try:
        page = reopened[0]
        text = page.get_text()
        assert PAGE_SECRET not in text
        assert KEEP in text
        annots = list(page.annots() or [])
        contents = [a.info.get("content", "") for a in annots]
        assert NOTE_SECRET not in contents
        assert NOTE_OUTSIDE in contents
        types = [a.type[1] for a in annots]
        assert "Text" in types
    finally:
        reopened.close()

    extracted = read.extract(out)["pages"][0]
    contents = [a["content"] for a in extracted["annotations"]]
    assert NOTE_SECRET not in contents
    assert NOTE_OUTSIDE in contents
    assert not _xref_has(out, NOTE_SECRET)
    assert _xref_has(out, NOTE_OUTSIDE)


def test_reply_of_in_region_note_is_stripped_even_if_outside(tmp_path):
    src = tmp_path / "thread.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), PAGE_SECRET, fontsize=12)
    page.insert_text((50, 400), KEEP, fontsize=12)
    parent = page.add_text_annot(pymupdf.Point(50, 70), NOTE_SECRET)
    reply = page.add_text_annot(pymupdf.Point(200, 400), REPLY_SECRET)
    reply.set_irt_xref(parent.xref)
    reply.update()
    doc.save(str(src))
    doc.close()
    out = tmp_path / "out.pdf"
    engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
        output=out,
    )
    reopened = pymupdf.open(out)
    try:
        contents = [a.info.get("content", "") for a in (reopened[0].annots() or [])]
        assert NOTE_SECRET not in contents
        assert REPLY_SECRET not in contents
        assert KEEP in reopened[0].get_text()
    finally:
        reopened.close()
    assert not _xref_has(out, NOTE_SECRET)
    assert not _xref_has(out, REPLY_SECRET)


def test_freetext_in_region_gone(tmp_path):
    src = tmp_path / "ft.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), PAGE_SECRET, fontsize=12)
    page.insert_text((50, 400), KEEP, fontsize=12)
    page.add_freetext_annot(pymupdf.Rect(50, 70, 220, 95), FREETEXT_SECRET, fontsize=11)
    doc.save(str(src))
    doc.close()
    out = tmp_path / "out.pdf"
    engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
        output=out,
    )
    reopened = pymupdf.open(out)
    try:
        contents = [a.info.get("content", "") for a in (reopened[0].annots() or [])]
        assert FREETEXT_SECRET not in contents
        assert FREETEXT_SECRET not in reopened[0].get_text()
        assert KEEP in reopened[0].get_text()
        assert PAGE_SECRET not in reopened[0].get_text()
    finally:
        reopened.close()
    assert not _xref_has(out, FREETEXT_SECRET)


def test_file_attachment_in_region_gone(tmp_path):
    src = tmp_path / "attach.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), PAGE_SECRET, fontsize=12)
    page.insert_text((50, 400), KEEP, fontsize=12)
    page.add_file_annot(pymupdf.Point(60, 80), ATTACH_SECRET, filename="secret.bin")
    doc.save(str(src))
    doc.close()
    out = tmp_path / "out.pdf"
    engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
        output=out,
    )
    reopened = pymupdf.open(out)
    try:
        for annot in reopened[0].annots() or []:
            if annot.type[0] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT:
                pytest.fail(f"file attachment survived: {annot.get_file()!r}")
        assert KEEP in reopened[0].get_text()
        assert PAGE_SECRET not in reopened[0].get_text()
    finally:
        reopened.close()
    assert not _xref_has(out, ATTACH_SECRET)


def test_form_value_in_region_gone_outside_field_remains(tmp_path):
    src = tmp_path / "form.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), PAGE_SECRET, fontsize=12)
    page.insert_text((50, 400), KEEP, fontsize=12)
    inside = pymupdf.Widget()
    inside.field_name = "inside_secret"
    inside.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    inside.rect = pymupdf.Rect(50, 90, 250, 110)
    inside.field_value = FIELD_SECRET
    page.add_widget(inside)
    outside = pymupdf.Widget()
    outside.field_name = "outside_ok"
    outside.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    outside.rect = pymupdf.Rect(50, 390, 250, 410)
    outside.field_value = "VISIBLE_FIELD"
    page.add_widget(outside)
    doc.save(str(src))
    doc.close()
    out = tmp_path / "out.pdf"
    engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
        output=out,
    )
    reopened = pymupdf.open(out)
    try:
        fields = {w.field_name: w.field_value for w in reopened[0].widgets()}
        assert "inside_secret" not in fields
        assert fields.get("outside_ok") == "VISIBLE_FIELD"
        assert PAGE_SECRET not in reopened[0].get_text()
        assert KEEP in reopened[0].get_text()
    finally:
        reopened.close()
    extracted = read.extract(out)["pages"][0]
    names = [f["name"] for f in extracted["form_fields"]]
    assert "inside_secret" not in names
    assert "outside_ok" in names
    assert not _xref_has(out, FIELD_SECRET)
    assert _xref_has(out, "VISIBLE_FIELD")


def test_unknown_intersecting_type_refuses(tmp_path):
    src = _make_region_pdf(tmp_path / "stamp.pdf")
    doc = pymupdf.open(src)
    doc[0].add_stamp_annot(pymupdf.Rect(50, 50, 140, 90), stamp=0)
    staged = tmp_path / "stamped.pdf"
    doc.save(str(staged))
    doc.close()
    before = staged.read_bytes()
    out = tmp_path / "out.pdf"
    with pytest.raises(OpError, match="Stamp"):
        engine.apply(
            staged,
            [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
            output=out,
        )
    assert staged.read_bytes() == before
    assert not out.exists()
    leftover = pymupdf.open(staged)[0]
    try:
        assert PAGE_SECRET in leftover.get_text()
        assert NOTE_SECRET in [
            a.info.get("content", "") for a in (leftover.annots() or [])
        ]
    finally:
        leftover.parent.close()


def test_unknown_ink_intersecting_refuses(tmp_path):
    src = make_unique_secret_pdf(tmp_path / "ink.pdf", secret=PAGE_SECRET)
    doc = pymupdf.open(src)
    page = doc[0]
    page.add_ink_annot([[[50, 50], [120, 120]]])
    staged = tmp_path / "inked.pdf"
    doc.save(str(staged))
    doc.close()
    out = tmp_path / "out.pdf"
    with pytest.raises(OpError, match="Ink"):
        engine.apply(
            staged,
            [{"op": "redact", "page": 1, "rect": REGION, "fill": [0, 0, 0]}],
            output=out,
        )
    assert not out.exists()


def test_apply_now_false_does_not_strip_notes(tmp_path):
    src = _make_region_pdf(tmp_path / "stage.pdf")
    out = tmp_path / "out.pdf"
    engine.apply(
        src,
        [{"op": "redact", "page": 1, "rect": REGION, "apply_now": False}],
        output=out,
    )
    reopened = pymupdf.open(out)
    try:
        contents = [a.info.get("content", "") for a in (reopened[0].annots() or [])]
        assert NOTE_SECRET in contents
        assert PAGE_SECRET in reopened[0].get_text()
        n_redact = sum(
            1
            for a in (reopened[0].annots() or [])
            if a.type[0] == pymupdf.PDF_ANNOT_REDACT
        )
        assert n_redact >= 1
    finally:
        reopened.close()


def test_pending_redact_annots_still_block_apply_now(tmp_path):
    """R14 / OMP-05: do not silently apply an unrelated staged redaction."""
    src = _make_region_pdf(tmp_path / "mix.pdf")
    doc = pymupdf.open(src)
    doc[0].add_redact_annot(pymupdf.Rect(40, 380, 200, 420), fill=(0, 0, 0))
    staged = tmp_path / "staged.pdf"
    doc.save(str(staged))
    doc.close()
    before = staged.read_bytes()
    out = tmp_path / "out.pdf"
    with pytest.raises(OpError, match="pending redaction"):
        engine.apply(
            staged,
            [{"op": "redact", "page": 1, "rect": REGION}],
            output=out,
        )
    assert staged.read_bytes() == before
    assert not out.exists()
    leftover = pymupdf.open(staged)[0]
    try:
        assert NOTE_SECRET in [
            a.info.get("content", "") for a in (leftover.annots() or [])
        ]
        assert PAGE_SECRET in leftover.get_text()
    finally:
        leftover.parent.close()


def test_gui_save_strips_note_in_redact_ghost(tmp_path):
    from omepreview.gui import Editor

    src = _make_region_pdf(tmp_path / "gui.pdf")
    ed = Editor(str(src), None)
    ed.pending.append(
        {
            "kind": "redact",
            "page": 0,
            "x0": float(REGION[0]),
            "y0": float(REGION[1]),
            "x1": float(REGION[2]),
            "y1": float(REGION[3]),
        }
    )
    result = ed.save_pending()
    path = Path(result["path"])
    reopened = pymupdf.open(path)
    try:
        text = reopened[0].get_text()
        assert PAGE_SECRET not in text
        assert KEEP in text
        contents = [a.info.get("content", "") for a in (reopened[0].annots() or [])]
        assert NOTE_SECRET not in contents
        assert NOTE_OUTSIDE in contents
    finally:
        reopened.close()
    ed.doc.close()
