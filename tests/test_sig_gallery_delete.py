"""Sign gallery on toolbar click, and Delete of a selected signature ghost."""

from pathlib import Path

from omepreview.view_gestures import (
    SELECT_HANDLE_PAD,
    delete_selected_ghost,
    hit_resize_handle,
    signature_ghost,
)


def test_delete_selected_ghost_removes_signature():
    g = signature_ghost(0, "default", 200.0, 100.0, aspect=0.5, width=160.0)
    other = signature_ghost(0, "initials", 40.0, 40.0, aspect=0.5, width=80.0)
    pending = [other, g]
    assert delete_selected_ghost(pending, g) is None
    assert pending == [other]
    assert delete_selected_ghost(pending, g) is g  # already gone
    assert delete_selected_ghost(pending, None) is None


def test_handle_hit_does_not_block_deleting_selected_ghost():
    """Corner handles select/resize; Delete still drops the same ghost object."""
    g = signature_ghost(0, "default", 200.0, 100.0, aspect=0.5, width=160.0)
    x0, y0 = g["x"], g["y"]
    x1, y1 = g["x"] + g["w"], g["y"] + g["h"]
    pad = SELECT_HANDLE_PAD
    assert hit_resize_handle(x1 + pad, y1 + pad, x0, y0, x1, y1) == "se"
    pending = [g]
    assert delete_selected_ghost(pending, g) is None
    assert pending == []


def test_delete_key_removes_ghost_before_sidebar_pages():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    body = text[text.index("def on_key") : text.index("keys.connect")]
    assert "ed.delete_selected()" in body
    assert body.index("ed.delete_selected()") < body.index("delete_selected_pages")
    assert body.index("ed.delete_selected()") < body.index("elif side_toggle.get_active():")


def test_sign_click_always_presents_gallery():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def on_sign_clicked")
    end = text.index('sign_btn.connect("clicked", on_sign_clicked)')
    body = text[start:end]
    assert "rebuild_sign_popover()" in body
    assert "_sign_pop_popup()" in body
    assert "GLib.idle_add" in body
    assert 'elif ed.tool == "sign"' not in body
    popup = text[text.index("def _sign_pop_popup") : text.index("def _flush_deferred_render")]
    assert "popover_can_popup" in popup
    assert "popover_is_alive" not in popup


def test_live_gtk_popover_capsule_is_not_treated_as_null():
    """PyGObject unnamed capsules print as NULL; that must not skip popup()."""
    import os

    import pytest

    if not os.environ.get("DISPLAY"):
        pytest.skip("needs a display")
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from omepreview.view_gestures import (
        gi_pointer_ok,
        popover_can_popup,
        popover_is_alive,
    )

    btn = Gtk.ToggleButton()
    pop = Gtk.Popover()
    assert "NULL" in str(pop.__gpointer__).upper()
    pop.set_parent(btn)
    assert gi_pointer_ok(pop) is True
    assert popover_can_popup(pop) is True
    assert popover_is_alive(pop) is False  # unrealized: autohide still skipped

