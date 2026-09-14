"""Live pinch math and signature drag payload — no GTK, no raster."""

from pathlib import Path

from omepreview.view_gestures import (
    SIG_DND_PREFIX,
    clamp_zoom_pct,
    compute_pinch_focus,
    current_zoom_pct,
    gi_pointer_ok,
    map_translate_coordinates,
    mapped_point,
    parse_signature_dnd,
    pinch_live_pct,
    pinch_pixmap_scale,
    page_y_at_focus,
    popover_can_popup,
    popover_is_alive,
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


def test_map_translate_coordinates_shapes():
    assert map_translate_coordinates(None) == (False, 0.0, 0.0)
    assert map_translate_coordinates(()) == (False, 0.0, 0.0)
    assert map_translate_coordinates((True, 3.0, 4.5)) == (True, 3.0, 4.5)
    assert map_translate_coordinates((False, 3.0, 4.5)) == (False, 3.0, 4.5)
    assert map_translate_coordinates((12.0, 34.0)) == (True, 12.0, 34.0)
    assert mapped_point((12.0, 34.0)) == (12.0, 34.0)
    assert mapped_point(None) is None
    assert mapped_point((False, 1.0, 2.0)) is None


class _FakeAdj:
    def __init__(self, value, page):
        self._value = value
        self._page = page

    def get_value(self):
        return self._value

    def get_page_size(self):
        return self._page


class _FakeGesture:
    def __init__(self, ok=True, cx=40.0, cy=80.0):
        self.ok, self.cx, self.cy = ok, cx, cy

    def get_bounding_box_center(self):
        return self.ok, self.cx, self.cy


class _FakeScroller:
    def __init__(self, mapped):
        self._mapped = mapped

    def translate_coordinates(self, _area, _cx, _cy):
        return self._mapped

    def get_width(self):
        return 400

    def get_height(self):
        return 300

    def get_hadjustment(self):
        return _FakeAdj(10.0, 400.0)

    def get_vadjustment(self):
        return _FakeAdj(20.0, 300.0)


def test_compute_pinch_focus_accepts_omarchy_2tuple():
    cy, xy = compute_pinch_focus(_FakeGesture(), _FakeScroller((12.0, 34.0)), object())
    assert cy == 80.0
    assert xy == (12.0, 34.0)


def test_compute_pinch_focus_accepts_gtk_3tuple():
    cy, xy = compute_pinch_focus(
        _FakeGesture(), _FakeScroller((True, 12.0, 34.0)), object()
    )
    assert cy == 80.0
    assert xy == (12.0, 34.0)


def test_compute_pinch_focus_none_falls_back_to_viewport_center():
    cy, xy = compute_pinch_focus(_FakeGesture(), _FakeScroller(None), object())
    assert cy == 80.0
    assert xy == (50.0, 100.0)


def test_compute_pinch_focus_tok_false_falls_back():
    cy, xy = compute_pinch_focus(
        _FakeGesture(), _FakeScroller((False, 1.0, 2.0)), object()
    )
    assert xy == (50.0, 100.0)


class _NullPopover:
    __gpointer__ = "NULL"

    def get_parent(self):
        raise AssertionError("must not call GTK on a NULL GI pointer")

    def get_realized(self):
        raise AssertionError("must not call GTK on a NULL GI pointer")


class _AlivePopover:
    __gpointer__ = "0xabc"

    def get_parent(self):
        return object()

    def get_realized(self):
        return True


class _UnrealizedPopover:
    __gpointer__ = "0xabc"

    def get_parent(self):
        return object()

    def get_realized(self):
        return False


class _OrphanPopover:
    __gpointer__ = "0xabc"

    def get_parent(self):
        return None

    def get_realized(self):
        return True


def test_popover_is_alive_skips_null_pointer_without_gtk_calls():
    assert gi_pointer_ok(_NullPopover()) is False
    assert popover_is_alive(_NullPopover()) is False
    assert popover_is_alive(None) is False
    assert popover_is_alive(_AlivePopover()) is True
    assert popover_is_alive(_UnrealizedPopover()) is False
    assert popover_is_alive(_OrphanPopover()) is False
    assert popover_can_popup(_NullPopover()) is False
    assert popover_can_popup(None) is False
    assert popover_can_popup(_AlivePopover()) is True
    assert popover_can_popup(_UnrealizedPopover()) is True
    assert popover_can_popup(_OrphanPopover()) is False


def test_pinch_begin_sets_state_after_focus():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    focus = text[text.index("def _pinch_focus") : text.index("def on_pinch_begin")]
    begin = text[text.index("def on_pinch_begin") : text.index("def on_pinch(_gesture, scale):")]
    assert "compute_pinch_focus" in focus
    assert "tok, ax, ay = mapped" not in text
    assert begin.index("_pinch_focus") < begin.index('pinch_state["start_pct"]')
    assert 'if sig_drag["active"]:' in begin


def test_sign_pop_autohide_and_popdown_are_guarded():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def rebuild_sign_popover():")
    end = text.index("def on_sign_clicked")
    body = text[start:end]
    assert "sign_pop.set_autohide(False)" not in body
    assert "sign_pop.set_autohide(True)" not in body
    assert "sign_pop.popdown()" not in body
    assert "_sign_pop_set_autohide(False)" in body
    assert "_sign_pop_set_autohide(True)" in body
    assert "_sign_pop_popdown()" in body
    assert "popover_is_alive" in text
    assert "if not _sign_pop_alive():" in text


def test_render_page_skips_overlay_resize_during_sig_drag():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def render_page(")
    end = text.index("# -- drawing")
    body = text[start:end]
    assert 'if sig_drag.get("active")' in body
    assert 'pinch_state["deferred_render"]' in body
