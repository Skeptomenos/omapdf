"""Empty launcher start: no file dialog, then Open from the editor."""

from __future__ import annotations

from pathlib import Path

from omepreview.gui import Editor
from omepreview.ops import OpError
from tests.data.make_docs import make_labeled_pdf


def test_editor_starts_empty_then_opens_a_path(tmp_path):
    ed = Editor(None, None)
    assert not ed.has_document()
    assert ed.page_count() == 0
    assert ed.path == ""
    pdf = make_labeled_pdf(tmp_path / "studio.pdf", page_count=2)
    ed.open_path(str(pdf))
    assert ed.has_document()
    assert ed.page_count() == 2
    assert Path(ed.path).name == "studio.pdf"


def test_editor_save_without_document_explains_open():
    ed = Editor(None, None)
    try:
        ed.save_pending()
    except OpError as exc:
        assert "Open" in str(exc) or "no PDF" in str(exc)
    else:
        raise AssertionError("empty editor must refuse save")


def test_gui_wires_in_app_open_and_ctrl_o():
    text = Path(__file__).resolve().parents[1].joinpath("src/omepreview/gui.py").read_text(
        encoding="utf-8"
    )
    assert "def pdf_open_dialog" in text
    assert "def choose_open" in text
    assert "Open PDF" in text
    assert "Gdk.KEY_o" in text
    assert "pick_pdf_path" not in text
    body = text[text.index("def on_key") : text.index("keys.connect")]
    assert "open_hook" in body
    assert body.index("KEY_o") < body.index("KEY_s")
