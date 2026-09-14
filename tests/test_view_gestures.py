"""Live pinch math and signature drag payload — no GTK, no raster."""

from pathlib import Path

from omepreview.view_gestures import (
    SIG_DND_PREFIX,
    clamp_zoom_pct,
    current_zoom_pct,
    parse_signature_dnd,
    pinch_live_pct,
    pinch_pixmap_scale,
    page_y_at_focus,
    scroll_to_keep_focus,
    signature_dnd_payload,
    signature_ghost,
)


def test_pinch_live_pct_clamps():
    assert pinch_live_pct(100.0, 1.0) == 100.0
    assert pinch_live_pct(100.0, 2.0) == 200.0
    assert pinch_live_pct(100.0, 8.0) == 400.0
    assert pinch_live_pct(100.0, 0.1) == 25.0


def test_pinch_pixmap_scale_is_relative_to_committed_raster():
    assert pinch_pixmap_scale(100.0, 150.0) == 1.5
    assert pinch_pixmap_scale(80.0, 80.0) == 1.0
    assert pinch_pixmap_scale(0.0, 100.0) == 1.0


def test_fit_page_zoom_pct_from_scale():
    # matrix zoom 1.0 ↔ 75% (100% is 96/72 CSS-px per PDF point)
    assert current_zoom_pct(None, 1.0) == 75.0
    assert current_zoom_pct(None, 96 / 72) == 100.0
    assert current_zoom_pct(200.0, 1.0) == 200.0


def test_clamp_zoom_pct():
    assert clamp_zoom_pct(10) == 25.0
    assert clamp_zoom_pct(999) == 400.0


def test_signature_dnd_roundtrip():
    payload = signature_dnd_payload("default")
    assert payload == f"{SIG_DND_PREFIX}default"
    assert parse_signature_dnd(payload) == "default"
    assert parse_signature_dnd("nope") is None
    assert parse_signature_dnd("") is None
    assert parse_signature_dnd(None) is None


def test_signature_dnd_from_store_path(tmp_path):
    svg = tmp_path / "Downloads" / "omapreview" / "signature" / "initials.svg"
    svg.parent.mkdir(parents=True)
    svg.write_text("<svg/>")
    assert parse_signature_dnd(str(svg)) == "initials"
    assert parse_signature_dnd(svg.as_uri()) == "initials"
    stray = tmp_path / "other.svg"
    stray.write_text("<svg/>")
    assert parse_signature_dnd(str(stray)) is None


def test_signature_ghost_centers_on_drop_point():
    g = signature_ghost(2, "default", 200.0, 100.0, aspect=0.5, width=160.0)
    assert g["kind"] == "sig"
    assert g["page"] == 2
    assert g["signature"] == "default"
    assert g["x"] == 120.0
    assert g["y"] == 60.0
    assert g["w"] == 160.0
    assert g["h"] == 80.0
    assert g["date"] is False


class _FakeFile:
    def __init__(self, path: Path):
        self._path = str(path)

    def get_path(self):
        return self._path


def test_signature_dnd_from_gio_file_like(tmp_path):
    svg = tmp_path / "signature" / "jane.svg"
    svg.parent.mkdir()
    svg.write_text("<svg/>")
    assert parse_signature_dnd(_FakeFile(svg)) == "jane"


def test_pinch_scale_changed_does_not_rerasterize_pdf():
    """ANR guard: scale-changed must transform the pixmap, not call render_page."""
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def on_pinch(_gesture, scale):")
    end = text.index("def commit_pinch_zoom():")
    body = text[start:end]
    assert "render_page()" not in body
    assert "queue_draw()" in body
    assert "pinch_pixmap_scale" in body


def test_scroll_to_keep_focus_holds_viewport_y():
    # page_y 200 at zoom 1, origin 40, viewport_y 100 → vscroll = 40+200-100 = 140
    assert page_y_at_focus(
        page_origin_y=40.0, zoom=1.0, vscroll=140.0, viewport_y=100.0
    ) == 200.0
    # after 2× zoom, same page_y at same viewport_y
    assert scroll_to_keep_focus(
        page_origin_y=40.0, zoom=2.0, page_y=200.0, viewport_y=100.0, vmax=10_000
    ) == 340.0
    assert scroll_to_keep_focus(
        page_origin_y=0.0, zoom=1.0, page_y=0.0, viewport_y=50.0, vmax=10
    ) == 0.0


def test_signature_place_does_not_use_gdk_drag_source():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def rebuild_sign_popover():")
    end = text.index("def on_sign_clicked")
    body = text[start:end]
    assert "Gtk.DragSource" not in body
    assert "Gtk.DropTarget" not in body
    assert "Gtk.GestureDrag" in body
    assert "place_named_signature" in body
    assert "GLib.idle_add" in body


def test_no_layout_debug_print():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    assert "omepreview layout:" not in src.read_text(encoding="utf-8")


def test_undo_arrowhead_is_up_left_redo_is_up_right():
    import cairo
    from omepreview.rail_icons import paint_redo, paint_undo

    def ink_points(painter):
        scale = 8
        n = 18 * scale
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, n, n)
        ctx = cairo.Context(surf)
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        ctx.scale(scale, scale)
        painter(ctx, (1, 1, 1, 1))
        buf = bytes(surf.get_data())
        stride = surf.get_stride()
        pts = []
        for y in range(n):
            row = y * stride
            for x in range(n):
                # CAIRO_FORMAT_ARGB32 little-endian: BGRA
                r = buf[row + x * 4 + 2]
                if r > 80:
                    pts.append((x, y))
        return pts

    undo = ink_points(paint_undo)
    redo = ink_points(paint_redo)
    assert undo and redo
    undo_top = min(y for _, y in undo)
    redo_top = min(y for _, y in redo)
    undo_top_xs = [x for x, y in undo if y <= undo_top + 8]
    redo_top_xs = [x for x, y in redo if y <= redo_top + 8]
    assert sum(undo_top_xs) / len(undo_top_xs) < 18 * 8 / 2
    assert sum(redo_top_xs) / len(redo_top_xs) > 18 * 8 / 2
    undo_bottom = max(y for _, y in undo)
    # Arrowhead lives in the upper half, not a down-pointing chevron.
    assert undo_top < undo_bottom * 0.45
