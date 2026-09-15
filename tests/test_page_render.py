"""Raster path must not double-apply /Rotate (90° must look 90°, not 180°)."""

from pathlib import Path

import pymupdf

from omepreview import engine
from omepreview.gui_pages import clear_thumb_dragging, insertion_marker_y
from omepreview.render import page_view_matrix, raster_page
from tests.data.make_docs import make_labeled_pdf


def test_page_view_matrix_is_scale_only():
    m = page_view_matrix(2.0)
    assert abs(m.a - 2.0) < 1e-9
    assert abs(m.d - 2.0) < 1e-9
    # No rotation component.
    assert abs(m.b) < 1e-9
    assert abs(m.c) < 1e-9


def test_raster_one_rotate_is_landscape_not_180(tmp_path):
    src = make_labeled_pdf(tmp_path / "p.pdf", page_count=1)
    out = tmp_path / "r90.pdf"
    engine.apply(src, [{"op": "rotate_pages", "pages": [1], "degrees": 90}], output=out)
    doc = pymupdf.open(out)
    page = doc[0]
    assert page.rotation == 90
    assert page.rect.width > page.rect.height
    pix = raster_page(page, 1.0)
    assert pix.width > pix.height
    doubled = page.get_pixmap(matrix=pymupdf.Matrix(1, 1).prerotate(page.rotation))
    assert doubled.width < doubled.height
    doc.close()


def test_four_right_rotates_return_to_portrait(tmp_path):
    src = make_labeled_pdf(tmp_path / "p.pdf", page_count=1)
    out = tmp_path / "r360.pdf"
    engine.apply(
        src,
        [{"op": "rotate_pages", "pages": [1], "degrees": 90}] * 4,
        output=out,
    )
    doc = pymupdf.open(out)
    page = doc[0]
    assert page.rotation == 0
    pix = raster_page(page, 1.0)
    assert pix.height > pix.width
    doc.close()


def test_gui_files_do_not_prerotate_page_rotation():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview"
    hits = []
    for name in ("gui.py", "gui_pages.py"):
        for i, line in enumerate((src / name).read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if "prerotate" in stripped:
                hits.append(f"{name}:{i}:{line.strip()}")
    assert hits == [], "get_pixmap already applies /Rotate:\n" + "\n".join(hits)


def test_insertion_marker_is_in_front_of_target():
    assert insertion_marker_y(40, 400) == 40
    assert insertion_marker_y(None, 400) == 400


def test_clear_thumb_dragging_skips_bool():
    """GTK drag-end passes delete_data: bool. Must not traceback."""
    clear_thumb_dragging(True)
    clear_thumb_dragging(False)
    clear_thumb_dragging(None)

    class _Row:
        def __init__(self):
            self.removed = []

        def remove_css_class(self, name):
            self.removed.append(name)

    row = _Row()
    clear_thumb_dragging(row)
    assert row.removed == ["omapdf-thumb-dragging"]


def test_drag_end_signature_keeps_widget_when_gtk_passes_bool():
    """Simulate Gtk.DragSource drag-end (source, drag, delete_data)."""
    class _Row:
        def __init__(self):
            self.removed = []

        def remove_css_class(self, name):
            self.removed.append(name)

    thumb_row = _Row()

    def on_drag_end(_src, _drag, _delete_data=False, *, thumb_row=thumb_row):
        clear_thumb_dragging(thumb_row)

    on_drag_end(object(), object(), True)
    on_drag_end(object(), object(), False)
    assert thumb_row.removed == ["omapdf-thumb-dragging", "omapdf-thumb-dragging"]
