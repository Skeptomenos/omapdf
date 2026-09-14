"""GTK-bound popover gateway — the only place that calls popup/popdown/autohide.

``gtk_popover_set_autohide`` unrealizes the widget. On GTK 4.22 a realized
popover can already have a dead native/surface; the call then SIGSEGVs.
Callers go through these helpers so a missing surface skips the GTK method.
"""

from __future__ import annotations

from .view_gestures import gi_pointer_ok, popover_allows, popover_native_surface

_open: set[int] = set()


def popover_busy() -> bool:
    """True while any popover we opened has not yet emitted ``closed``."""
    return bool(_open)


def _target(widget):
    getter = getattr(widget, "get_popover", None)
    if callable(getter):
        try:
            inner = getter()
        except Exception:
            inner = None
        if inner is not None:
            return inner
    return widget


def _mark_open(widget) -> None:
    _open.add(id(widget))
    if getattr(widget, "_omepreview_closed_hook", False):
        return

    def _on_closed(*_a, w=widget):
        _open.discard(id(w))

    try:
        widget.connect("closed", _on_closed)
        widget._omepreview_closed_hook = True
    except Exception:
        return


def popover_try_popup(widget) -> bool:
    """Show *widget* (a Gtk.Popover or MenuButton). False if skipped."""
    if widget is None or not gi_pointer_ok(widget):
        return False
    target = _target(widget)
    if not popover_allows(target, "popup"):
        return False
    try:
        widget.popup()
        _mark_open(target)
        return True
    except Exception:
        return False


def popover_try_popdown(widget) -> bool:
    """Hide *widget* if it still has a live GdkSurface. False if skipped."""
    if widget is None:
        return False
    target = _target(widget)
    if not popover_allows(target, "popdown"):
        return False
    try:
        target.popdown()
        return True
    except Exception:
        return False


def popover_try_set_autohide(widget, value: bool) -> bool:
    """Set autohide only before the popover is mapped.

    Toggling autohide on a shown popover is the SEGV path
    (``gtk_popover_set_autohide`` → ``gtk_widget_unrealize``). Drag handlers
    must not call this.
    """
    if widget is None or not gi_pointer_ok(widget):
        return False
    get_realized = getattr(widget, "get_realized", None)
    if callable(get_realized):
        try:
            if get_realized():
                return False
        except Exception:
            return False
    _native, surface = popover_native_surface(widget)
    if surface is not None:
        # Already mapped: gtk_popover_set_autohide unrealizes and SEGVs
        # on a realized-but-nativeless widget.
        return False
    try:
        widget.set_autohide(value)
        return True
    except Exception:
        return False
