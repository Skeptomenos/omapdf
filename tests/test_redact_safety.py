"""R01 / R02 / R14 / R24 — redaction save/share safety."""

from pathlib import Path

import pymupdf
import pytest

from omepreview import engine
from omepreview.ops import OpError
from omepreview.redact_io import (
    redact_item_to_op,
    share_target_path,
    unused_sibling,
)
from tests.data.make_docs import make_repeated_word_pdf, make_unique_secret_pdf

SECRET = "ZXQ-R01-SECRET-7f3a9c"


def _ghost_for_rect(rect, page=0, match=None) -> dict:
    item = {
        "kind": "redact",
        "page": page,
        "x0": float(rect.x0),
        "y0": float(rect.y0),
        "x1": float(rect.x1),
        "y1": float(rect.y1),
    }
    if match is not None:
        item["match"] = match
    return item


def test_unused_sibling_skips_existing(tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 x")
    taken = tmp_path / "doc_redacted.pdf"
    taken.write_bytes(b"sentinel")
    dest = unused_sibling(src, "_redacted")
    assert dest == tmp_path / "doc_redacted-2.pdf"
    assert taken.read_bytes() == b"sentinel"


def test_redact_item_to_op_ignores_match():
    item = {
        "kind": "redact",
        "page": 0,
        "x0": 10,
        "y0": 20,
        "x1": 30,
        "y1": 40,
        "match": "ALPHAWORD",
    }
    op = redact_item_to_op(item)
    assert "match" not in op
    assert op["rect"] == [10.0, 20.0, 30.0, 40.0]
    assert op["page"] == 1


def test_one_occurrence_does_not_redact_siblings(tmp_path):
    """R02: selecting the middle repeated word leaves the other two."""
    src = make_repeated_word_pdf(tmp_path / "rep.pdf", word="ALPHAWORD", count=3)
    doc = pymupdf.open(src)
    rects = doc[0].search_for("ALPHAWORD")
    assert len(rects) == 3
    doc.close()
    op = redact_item_to_op(_ghost_for_rect(rects[1], match="ALPHAWORD"))
    out = tmp_path / "out.pdf"
    engine.apply(src, [op], output=out)
    text = pymupdf.open(out)[0].get_text()
    assert text.count("ALPHAWORD") == 2
    assert "KEEP-VISIBLE" in text


def test_gui_to_ops_never_emits_redact_match():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    body = text[text.index("def to_ops") : text.index("def item_rect")]
    assert "redact_item_to_op" in body
    assert '"match": it["match"]' not in body
    assert 'it.get("match")' not in body


def test_unapproved_preexisting_redaction_is_not_applied(tmp_path):
    """R14: applying SECRET must not also apply a pending OTHER annot."""
    src = make_unique_secret_pdf(tmp_path / "mix.pdf", secret=SECRET)
    doc = pymupdf.open(src)
    page = doc[0]
    page.insert_text((72, 200), "OTHERTOKEN")
    other = page.search_for("OTHERTOKEN")[0]
    page.add_redact_annot(other, fill=(0, 0, 0))
    tmp = tmp_path / "mix-annot.pdf"
    doc.save(str(tmp))
    doc.close()
    before = tmp.read_bytes()
    out = tmp_path / "out.pdf"
    with pytest.raises(OpError, match="pending redaction"):
        engine.apply(
            tmp,
            [{"op": "redact", "page": 1, "match": SECRET}],
            output=out,
        )
    assert tmp.read_bytes() == before
    assert not out.exists()
    leftover = pymupdf.open(tmp)[0].get_text()
    assert SECRET in leftover
    assert "OTHERTOKEN" in leftover


def test_apply_now_false_can_stage_beside_existing(tmp_path):
    src = make_unique_secret_pdf(tmp_path / "stage.pdf", secret=SECRET)
    doc = pymupdf.open(src)
    page = doc[0]
    page.insert_text((72, 200), "OTHERTOKEN")
    other = page.search_for("OTHERTOKEN")[0]
    page.add_redact_annot(other, fill=(0, 0, 0))
    staged = tmp_path / "staged.pdf"
    doc.save(str(staged))
    doc.close()
    out = tmp_path / "out.pdf"
    engine.apply(
        staged,
        [{"op": "redact", "page": 1, "match": SECRET, "apply_now": False}],
        output=out,
    )
    page = pymupdf.open(out)[0]
    n_redact = sum(1 for a in (page.annots() or []) if a.type[0] == pymupdf.PDF_ANNOT_REDACT)
    assert n_redact >= 2
    text = page.get_text()
    assert SECRET in text
    assert "OTHERTOKEN" in text


def test_failed_redact_save_does_not_destroy_existing_copy(tmp_path, monkeypatch):
    """R24: sentinel *_redacted.pdf survives a failed save."""
    from omepreview.gui import Editor

    src = make_unique_secret_pdf(tmp_path / "doc.pdf", secret=SECRET)
    sentinel = tmp_path / "doc_redacted.pdf"
    sentinel.write_bytes(b"%PDF-SENTINEL-R24\n")
    ed = Editor(str(src), None)
    rect = ed.doc[0].search_for(SECRET)[0]
    ed.pending.append(_ghost_for_rect(rect, match=SECRET))

    def boom(*_a, **_k):
        raise OpError("injected failure")

    monkeypatch.setattr(engine, "apply", boom)
    with pytest.raises(OpError, match="injected failure"):
        ed.save_pending()
    assert sentinel.read_bytes() == b"%PDF-SENTINEL-R24\n"
    assert not (tmp_path / "doc_redacted-2.pdf").exists()
    ed.doc.close()


def test_save_switches_editor_to_redacted_copy(tmp_path):
    """R01: after redact Save, the active path is the copy without the secret."""
    from omepreview.gui import Editor

    src = make_unique_secret_pdf(tmp_path / "doc.pdf", secret=SECRET)
    ed = Editor(str(src), None)
    rect = ed.doc[0].search_for(SECRET)[0]
    ed.pending.append(_ghost_for_rect(rect, match=SECRET))
    result = ed.save_pending()
    assert Path(result["path"]).name == "doc_redacted.pdf"
    assert Path(ed.path).resolve() == Path(result["path"]).resolve()
    assert SECRET not in pymupdf.open(ed.path)[0].get_text()
    assert SECRET in pymupdf.open(src)[0].get_text()
    assert "KEEP-VISIBLE" in pymupdf.open(ed.path)[0].get_text()
    shared = share_target_path(ed.path, flatten=False)
    assert shared.resolve() == Path(ed.path).resolve()
    assert SECRET not in pymupdf.open(shared)[0].get_text()
    flat = share_target_path(ed.path, flatten=True, flatten_fn=engine.flatten)
    assert SECRET not in pymupdf.open(flat)[0].get_text()
    assert flat.name == "doc_redacted-final.pdf"
    taken = Path(ed.path).with_name("doc_redacted-final.pdf")
    assert taken.exists()
    again = share_target_path(ed.path, flatten=True, flatten_fn=engine.flatten)
    assert again.name == "doc_redacted-final-2.pdf"
    assert SECRET not in pymupdf.open(again)[0].get_text()
    ed.doc.close()


def test_save_does_not_overwrite_existing_redacted_name(tmp_path):
    from omepreview.gui import Editor

    src = make_unique_secret_pdf(tmp_path / "doc.pdf", secret=SECRET)
    sentinel = tmp_path / "doc_redacted.pdf"
    sentinel.write_bytes(b"%PDF-SENTINEL-R24\n")
    ed = Editor(str(src), None)
    rect = ed.doc[0].search_for(SECRET)[0]
    ed.pending.append(_ghost_for_rect(rect))
    result = ed.save_pending()
    assert Path(result["path"]).name == "doc_redacted-2.pdf"
    assert sentinel.read_bytes() == b"%PDF-SENTINEL-R24\n"
    assert SECRET not in pymupdf.open(result["path"])[0].get_text()
    ed.doc.close()
