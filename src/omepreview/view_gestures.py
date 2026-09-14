"""Live pinch zoom + signature drag-and-drop helpers (no GTK).

Pinch must not re-rasterize the PDF on every scale-changed event — that
freezes the GTK main loop. These helpers compute a cheap cairo scale for
the current paper pixmap and a clamped zoom percent to commit on gesture
end. Signature DND uses a private text payload so a popover drag can drop
onto the page as a ``place_signature`` ghost.
"""

from __future__ import annotations

import math
from pathlib import Path
from urllib.parse import unquote, urlparse

SIG_DND_PREFIX = "omepreview-sig:"
ZOOM_MIN_PCT = 25.0
ZOOM_MAX_PCT = 400.0
SIG_GHOST_WIDTH = 160.0
SIG_MIN_WIDTH = 24.0
# Selection chrome is drawn in PDF points (then scaled by zoom). Pad matches
# the blue rect around a selected ghost; visual handles sit on its corners.
SELECT_HANDLE_PAD = 4.0
HANDLE_VISUAL_HALF = 3.2
HANDLE_HIT_RADIUS = 10.0
HANDLE_HIT_SCREEN_PX = 14.0
RESIZE_HANDLES = ("nw", "ne", "sw", "se")


def current_zoom_pct(zoom_pct: float | None, zoom: float) -> float:
    """Committed zoom percent; fit-page uses the live ``zoom`` scale."""
    if zoom_pct is not None:
        return zoom_pct
    return zoom / (96 / 72) * 100


def clamp_zoom_pct(pct: float) -> float:
    return max(ZOOM_MIN_PCT, min(ZOOM_MAX_PCT, pct))


def pinch_live_pct(start_pct: float, scale: float) -> float:
    """Zoom percent implied by Gtk.GestureZoom's total scale since begin."""
    return clamp_zoom_pct(start_pct * scale)


def pinch_pixmap_scale(committed_pct: float, live_pct: float) -> float:
    """Cairo extra scale for the already-rasterized paper pixmap."""
    if committed_pct <= 0:
        return 1.0
    return live_pct / committed_pct


def page_y_at_focus(
    *,
    page_origin_y: float,
    zoom: float,
    vscroll: float,
    viewport_y: float,
) -> float:
    """PDF-space Y (top-left origin) under a scroller-relative viewport Y."""
    if zoom <= 0:
        return 0.0
    return (vscroll + viewport_y - page_origin_y) / zoom


def scroll_to_keep_focus(
    *,
    page_origin_y: float,
    zoom: float,
    page_y: float,
    viewport_y: float,
    vmax: float,
) -> float:
    """vadjustment so ``page_y`` stays at the same screen height ``viewport_y``."""
    target = page_origin_y + page_y * zoom - viewport_y
    if vmax < 0:
        vmax = 0.0
    return max(0.0, min(vmax, target))


def map_translate_coordinates(mapped) -> tuple[bool, float, float]:
    """Normalize ``Widget.translate_coordinates()`` across GTK / PyGObject.

    GTK 4 GIR usually returns ``(ok, x, y)``. Omarchy GTK 4.22 / pygobject
    3.56 returned a 2-tuple ``(x, y)``; unpacking that as three values raised
    ``ValueError`` in the pinch handler. ``None`` / empty means failure.
    """
    if mapped is None:
        return False, 0.0, 0.0
    if not isinstance(mapped, (tuple, list)):
        return False, 0.0, 0.0
    n = len(mapped)
    if n == 3:
        tok, ax, ay = mapped
        return bool(tok), float(ax), float(ay)
    if n == 2:
        ax, ay = mapped
        return True, float(ax), float(ay)
    return False, 0.0, 0.0


def mapped_point(mapped) -> tuple[float, float] | None:
    """Return dest ``(x, y)`` when ``translate_coordinates`` succeeded."""
    ok, ax, ay = map_translate_coordinates(mapped)
    if not ok:
        return None
    return ax, ay


def compute_pinch_focus(gesture, scroller, area) -> tuple[float, tuple[float, float]]:
    """Scroller-relative Y and drawing-area XY of a pinch (else viewport center).

    Duck-typed: ``gesture.get_bounding_box_center()``, scroller adjustments /
    ``translate_coordinates``, ``get_width`` / ``get_height``. Never raises on
    a 2-tuple map result. Callers must not set ``pinch_state`` until this
    returns.
    """
    vadj = scroller.get_vadjustment()
    hadj = scroller.get_hadjustment()
    vw = float(hadj.get_page_size() or scroller.get_width() or 1.0)
    vh = float(vadj.get_page_size() or scroller.get_height() or 1.0)
    try:
        ok, cx, cy = gesture.get_bounding_box_center()
    except Exception:
        ok, cx, cy = False, 0.0, 0.0
    if not ok:
        cx, cy = vw / 2.0, vh / 2.0
    mapped = None
    try:
        mapped = scroller.translate_coordinates(area, cx, cy)
    except Exception:
        mapped = None
    tok, ax, ay = map_translate_coordinates(mapped)
    if tok:
        return float(cy), (ax, ay)
    return float(cy), (
        float(hadj.get_value()) + float(cx),
        float(vadj.get_value()) + float(cy),
    )


def gi_pointer_ok(widget) -> bool:
    """True if a PyGObject wrapper still holds a non-NULL C pointer.

    A destroyed Gtk widget keeps a Python wrapper whose ``__gpointer__``
    capsule prints as ``NULL``. Calling GTK methods on it SIGSEGVs.
    Objects without ``__gpointer__`` are treated as duck-typed test doubles.
    """
    if widget is None:
        return False
    if not hasattr(widget, "__gpointer__"):
        return True
    ptr = widget.__gpointer__
    if ptr is None:
        return False
    if "NULL" in str(ptr).upper():
        return False
    return True


def popover_is_alive(widget) -> bool:
    """True when a popover is safe to ``set_autohide`` / ``popdown``.

    Requires a non-NULL GI pointer, a parent, and ``get_realized()`` when
    that method exists. Any GTK call is skipped when the pointer is NULL —
    ``get_realized()`` itself can SEGV on a NULL instance.
    """
    if not gi_pointer_ok(widget):
        return False
    try:
        if widget.get_parent() is None:
            return False
        realized = getattr(widget, "get_realized", None)
        if not callable(realized):
            return True
        return bool(realized())
    except Exception:
        return False


def signature_dnd_payload(name: str) -> str:
    return f"{SIG_DND_PREFIX}{name}"


def parse_signature_dnd(value: object) -> str | None:
    """Return a stored signature name from a drag payload, or None."""
    if value is None:
        return None
    getter = getattr(value, "get_path", None)
    if callable(getter):
        path = getter()
        if path:
            return _name_from_signature_file(Path(path))
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(SIG_DND_PREFIX):
        name = text[len(SIG_DND_PREFIX) :].strip()
        return name or None
    if text.startswith("file:"):
        path = Path(unquote(urlparse(text).path))
        return _name_from_signature_file(path)
    return _name_from_signature_file(Path(text))


def _name_from_signature_file(path: Path) -> str | None:
    if path.suffix.lower() not in {".svg", ".png"}:
        return None
    if path.parent.name not in {"signature", "signatures"}:
        return None
    name = path.stem
    if not name or name.startswith(".") or "/" in name:
        return None
    return name


def signature_ghost(
    page_no: int,
    name: str,
    px: float,
    py: float,
    aspect: float,
    width: float = SIG_GHOST_WIDTH,
) -> dict:
    """Pending ``sig`` item centered on a page point (top-left origin)."""
    return {
        "kind": "sig",
        "page": page_no,
        "x": px - width / 2,
        "y": py - width * aspect / 2,
        "w": width,
        "h": width * aspect,
        "date": False,
        "signature": name,
    }


def handle_hit_radius(zoom: float) -> float:
    """Page-space radius so handles stay hittable at low zoom (~14 CSS px)."""
    z = zoom if zoom > 0 else 1.0
    return max(HANDLE_HIT_RADIUS, HANDLE_HIT_SCREEN_PX / z)


def selection_handle_centers(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    pad: float = SELECT_HANDLE_PAD,
) -> dict[str, tuple[float, float]]:
    """Corner-handle centers matching the selected-ghost chrome in the editor."""
    return {
        "nw": (x0 - pad, y0 - pad),
        "ne": (x1 + pad, y0 - pad),
        "sw": (x0 - pad, y1 + pad),
        "se": (x1 + pad, y1 + pad),
    }


def hit_resize_handle(
    px: float,
    py: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    radius: float = HANDLE_HIT_RADIUS,
    pad: float = SELECT_HANDLE_PAD,
) -> str | None:
    """Return ``nw``/``ne``/``sw``/``se`` if ``(px, py)`` hits a corner handle."""
    best: str | None = None
    best_d = radius
    for name, (hx, hy) in selection_handle_centers(x0, y0, x1, y1, pad).items():
        d = math.hypot(px - hx, py - hy)
        if d <= best_d:
            best_d = d
            best = name
    return best


def resize_signature_keep_aspect(
    x: float,
    y: float,
    w: float,
    h: float,
    handle: str,
    px: float,
    py: float,
    *,
    aspect: float | None = None,
    min_width: float = SIG_MIN_WIDTH,
) -> tuple[float, float, float, float]:
    """New ``(x, y, w, h)`` after dragging ``handle`` to ``(px, py)``.

    The opposite corner stays fixed. Width/height keep ``aspect`` (default
    ``h / w``). Dragging past the anchor clamps to ``min_width`` rather than
    flipping the rect.
    """
    if handle not in RESIZE_HANDLES:
        raise ValueError(f"unknown resize handle {handle!r}")
    if w <= 0:
        w = min_width
    if aspect is None:
        aspect = h / w if w else 1.0
    if aspect <= 0:
        aspect = 1.0
    x1, y1 = x + w, y + h
    if handle == "se":
        ax, ay = x, y
        raw_w, raw_h = px - ax, py - ay
    elif handle == "nw":
        ax, ay = x1, y1
        raw_w, raw_h = ax - px, ay - py
    elif handle == "ne":
        ax, ay = x, y1
        raw_w, raw_h = px - ax, ay - py
    else:  # sw
        ax, ay = x1, y
        raw_w, raw_h = ax - px, py - ay
    new_w = max(raw_w, raw_h / aspect, min_width)
    new_h = new_w * aspect
    if handle == "se":
        return ax, ay, new_w, new_h
    if handle == "nw":
        return ax - new_w, ay - new_h, new_w, new_h
    if handle == "ne":
        return ax, ay - new_h, new_w, new_h
    return ax - new_w, ay, new_w, new_h
