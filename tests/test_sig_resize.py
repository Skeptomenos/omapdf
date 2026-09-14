"""Corner-handle hit-test and aspect-locked signature ghost resize (no GTK)."""

from pathlib import Path

import pytest

from omepreview.view_gestures import (
    SELECT_HANDLE_PAD,
    SIG_MIN_WIDTH,
    handle_hit_radius,
    hit_resize_handle,
    resize_signature_keep_aspect,
    selection_handle_centers,
    signature_ghost,
)


def _rect():
    # 160×80, top-left (100, 50) — same aspect as a 2:1 signature.
    return 100.0, 50.0, 260.0, 130.0


def test_handle_centers_match_selection_chrome():
    x0, y0, x1, y1 = _rect()
    pad = SELECT_HANDLE_PAD
    assert selection_handle_centers(x0, y0, x1, y1) == {
        "nw": (x0 - pad, y0 - pad),
        "ne": (x1 + pad, y0 - pad),
        "sw": (x0 - pad, y1 + pad),
        "se": (x1 + pad, y1 + pad),
    }


def test_hit_resize_handle_corners_not_body():
    x0, y0, x1, y1 = _rect()
    centers = selection_handle_centers(x0, y0, x1, y1)
    for name, (hx, hy) in centers.items():
        assert hit_resize_handle(hx, hy, x0, y0, x1, y1) == name
        assert hit_resize_handle(hx + 0.5, hy - 0.5, x0, y0, x1, y1) == name
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert hit_resize_handle(cx, cy, x0, y0, x1, y1) is None


def test_hit_resize_handle_outside_body_still_counts():
    x0, y0, x1, y1 = _rect()
    pad = SELECT_HANDLE_PAD
    # Just outside the body pad, still on the SE handle.
    assert hit_resize_handle(x1 + pad, y1 + pad, x0, y0, x1, y1) == "se"
    assert hit_resize_handle(x1 + pad + 11, y1 + pad, x0, y0, x1, y1) is None


def test_resize_se_keeps_aspect_and_nw_anchor():
    x, y, w, h = 100.0, 50.0, 160.0, 80.0
    nx, ny, nw, nh = resize_signature_keep_aspect(
        x, y, w, h, "se", 100.0 + 320.0, 50.0 + 80.0
    )
    assert (nx, ny) == (100.0, 50.0)
    assert nw == 320.0
    assert nh == pytest.approx(160.0)
    assert nh / nw == pytest.approx(h / w)


def test_resize_nw_keeps_aspect_and_se_anchor():
    x, y, w, h = 100.0, 50.0, 160.0, 80.0
    nx, ny, nw, nh = resize_signature_keep_aspect(x, y, w, h, "nw", 20.0, 10.0)
    assert (nx + nw, ny + nh) == pytest.approx((260.0, 130.0))
    assert nw / nh == pytest.approx(w / h)


def test_resize_ne_and_sw_keep_aspect():
    x, y, w, h = 100.0, 50.0, 160.0, 80.0
    nx, ny, nw, nh = resize_signature_keep_aspect(x, y, w, h, "ne", 420.0, 10.0)
    assert nx == 100.0
    assert ny + nh == pytest.approx(130.0)
    assert nh / nw == pytest.approx(0.5)
    nx, ny, nw, nh = resize_signature_keep_aspect(x, y, w, h, "sw", 20.0, 210.0)
    assert nx + nw == pytest.approx(260.0)
    assert ny == 50.0
    assert nh / nw == pytest.approx(0.5)


def test_resize_clamps_min_width_instead_of_flipping():
    x, y, w, h = 100.0, 50.0, 160.0, 80.0
    nx, ny, nw, nh = resize_signature_keep_aspect(x, y, w, h, "se", 90.0, 40.0)
    assert nw == SIG_MIN_WIDTH
    assert nh == pytest.approx(SIG_MIN_WIDTH * 0.5)
    assert (nx, ny) == (100.0, 50.0)


def test_resize_unknown_handle_raises():
    with pytest.raises(ValueError, match="unknown resize handle"):
        resize_signature_keep_aspect(0, 0, 10, 5, "mid", 1, 1)


def test_handle_hit_radius_grows_at_low_zoom():
    assert handle_hit_radius(1.0) == 14.0
    assert handle_hit_radius(0.5) == 28.0
    assert handle_hit_radius(4.0) == 10.0


def test_ghost_to_ops_width_tracks_resize():
    g = signature_ghost(0, "default", 200.0, 100.0, aspect=0.5, width=160.0)
    nx, ny, nw, nh = resize_signature_keep_aspect(
        g["x"], g["y"], g["w"], g["h"], "se", g["x"] + 240.0, g["y"] + 40.0
    )
    g.update(x=nx, y=ny, w=nw, h=nh)
    assert g["w"] == 240.0
    assert g["h"] == pytest.approx(120.0)


def test_gui_select_drag_resizes_on_handle_not_only_move():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    begin = text[text.index("def on_drag_begin") : text.index("def on_drag_update")]
    update = text[text.index("def on_drag_update") : text.index("def on_drag_end")]
    assert "hit_sig_handle" in begin
    assert "drag_resize" in begin
    assert "resize_signature_keep_aspect" in update
    assert update.index("ed.drag_resize") < update.index("ed.move_item")
    assert "ed.drag_resize = None" in text[text.index("def on_drag_end") :]
