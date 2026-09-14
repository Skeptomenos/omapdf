"""Live pinch zoom + signature drag-and-drop helpers (no GTK).

Pinch must not re-rasterize the PDF on every scale-changed event — that
freezes the GTK main loop. These helpers compute a cheap cairo scale for
the current paper pixmap and a clamped zoom percent to commit on gesture
end. Signature DND uses a private text payload so a popover drag can drop
onto the page as a ``place_signature`` ghost.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

SIG_DND_PREFIX = "omepreview-sig:"
ZOOM_MIN_PCT = 25.0
ZOOM_MAX_PCT = 400.0
SIG_GHOST_WIDTH = 160.0


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
