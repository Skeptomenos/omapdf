"""omepreview edit — the GTK4 editor.

A thin client over the op engine, like everything else: tools build *pending
items* (ghosts) that are drawn over the rendered page; Save converts them to
ops and hands them to engine.apply(). Until Save, everything is draggable —
including proposals an agent supplies via --ops, which load as ghosts for the
human to nudge and confirm.

Toolbar lineage: PDFfiller's edit bar (Select/Text/Sign/Check/Cross/Undo) ×
omasnap's annotation bar (pen, shapes, minimal chrome).
"""

from __future__ import annotations

import copy
import io
import json
import math
import os
import shutil
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
try:
    gi.require_foreign("cairo")
except (ImportError, ValueError) as exc:
    raise SystemExit(
        "omepreview edit needs PyGObject cairo integration — install python3-gi-cairo "
        "(Debian/Ubuntu) or ensure python-gobject is built with cairo support."
    ) from exc
import cairo
import pymupdf
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo

from . import engine
from . import gui_pages
from .crop_coords import transform_pending_for_crop
from . import signature as sig_store
from .page_preview import PagePreviewState
from .view_gestures import (
    compute_pinch_focus,
    current_zoom_pct,
    mapped_point,
    page_y_at_focus,
    pinch_live_pct,
    pinch_pixmap_scale,
    popover_is_alive,
    scroll_to_keep_focus,
    signature_ghost,
)
from .rail_icons import paint_redo as paint_redo_glyph
from .rail_icons import paint_undo as paint_undo_glyph
from .window_controls import window_controls_enabled

CHECK = [[(0.0, 7.0), (4.5, 12.0), (14.0, 0.0)]]
CROSS = [[(0.0, 0.0), (12.0, 12.0)], [(12.0, 0.0), (0.0, 12.0)]]
STAMP_SIZE = 16.0  # points
CHECK_COLOR = (0.18, 0.62, 0.31)
CROSS_COLOR = (0.84, 0.27, 0.27)
PEN_WIDTH = 2.0
PEN_COLORS = [
    ("Black", (0.1, 0.1, 0.1)),
    ("Red", (0.75, 0.1, 0.1)),
    ("Blue", (0.13, 0.35, 0.85)),
    ("Green", (0.15, 0.55, 0.3)),
    ("Orange", (0.95, 0.55, 0.05)),
]
NOTE_SIZE = 20.0  # points, drawn sticky-note glyph
SELECT_COLOR = (0.15, 0.45, 0.95)
PAGE_MARGIN_PX = 48
SHADOWS_LIGHT = ((16, 22, 0.12), (3, 5, 0.08), (1, 1.2, 0.14))
SHADOWS_DARK = ((18, 26, 0.55), (4, 7, 0.35), (1, 1.5, 0.5))
PAPER_EDGE_ALPHA = 0.08


def _norm_rect(it: dict) -> tuple[float, float, float, float]:
    return (
        min(it["x0"], it["x1"]),
        min(it["y0"], it["y1"]),
        max(it["x0"], it["x1"]),
        max(it["y0"], it["y1"]),
    )


def _draw_shape(
    ctx,
    shape: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: tuple[float, ...],
    width: float,
    alpha: float = 1.0,
):
    ctx.set_source_rgba(color[0], color[1], color[2], alpha)
    ctx.set_line_width(width)
    if shape in ("line", "arrow"):
        ctx.move_to(x0, y0)
        ctx.line_to(x1, y1)
        ctx.stroke()
        if shape == "arrow":
            ang = math.atan2(y1 - y0, x1 - x0)
            ah = max(8.0, width * 4)
            for da in (2.4, -2.4):
                ctx.move_to(x1, y1)
                ctx.line_to(
                    x1 - ah * math.cos(ang + da),
                    y1 - ah * math.sin(ang + da),
                )
                ctx.stroke()
    elif shape == "rect":
        rx0, ry0, rx1, ry1 = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        ctx.rectangle(rx0, ry0, rx1 - rx0, ry1 - ry0)
        ctx.stroke()
    else:
        rx0, ry0, rx1, ry1 = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        mx, my = (rx0 + rx1) / 2, (ry0 + ry1) / 2
        rw, rh = max((rx1 - rx0) / 2, 1), max((ry1 - ry0) / 2, 1)
        ctx.save()
        ctx.translate(mx, my)
        ctx.scale(rw, rh)
        ctx.arc(0, 0, 1, 0, 2 * math.pi)
        ctx.stroke()
        ctx.restore()


def _luminance(r: float, g: float, b: float) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _color_scheme_is_dark() -> bool:
    """Honor Omarchy/GNOME color-scheme (same source as omarchy-theme-set-gnome)."""
    try:
        iface = Gio.Settings.new("org.gnome.desktop.interface")
        scheme = iface.get_string("color-scheme")
        if scheme == "prefer-dark":
            return True
        if scheme == "prefer-light":
            return False
    except Exception:
        pass
    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is not None:
        return gtk_settings.get_property("gtk-application-prefer-dark-theme")
    return False


def _sync_color_scheme() -> None:
    dark = _color_scheme_is_dark()
    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is not None:
        gtk_settings.set_property("gtk-application-prefer-dark-theme", dark)


def _theme_colors(widget: Gtk.Widget) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    style = widget.get_style_context()
    bg = style.lookup_color("theme_bg_color")[1]
    fg = style.lookup_color("theme_fg_color")[1]
    return (bg.red, bg.green, bg.blue), (fg.red, fg.green, fg.blue)


def _desk_rgb(bg: tuple[float, float, float], light: bool) -> tuple[float, float, float]:
    factor = 0.95 if light else 0.62
    return tuple(max(0.0, min(1.0, c * factor)) for c in bg)


def _draw_paper_shadow(
    ctx: cairo.Context,
    ox: float,
    oy: float,
    pw: float,
    ph: float,
    layers: tuple[tuple[float, float, float], ...],
) -> None:
    for dy, blur, alpha in layers:
        spread = blur * 0.45
        ctx.set_source_rgba(0, 0, 0, alpha)
        ctx.rectangle(
            ox - spread * 0.5,
            oy + dy - spread * 0.3,
            pw + spread,
            ph + spread * 0.6,
        )
        ctx.fill()


def _draw_folio(
    ctx: cairo.Context,
    text: str,
    x: float,
    y: float,
    fg: tuple[float, float, float],
    alpha: float,
) -> None:
    layout = PangoCairo.create_layout(ctx)
    layout.set_font_description(Pango.FontDescription("monospace 10.5"))
    layout.set_text(text, -1)
    _, th = layout.get_pixel_size()
    ctx.move_to(x, y - th)
    ctx.set_source_rgba(fg[0], fg[1], fg[2], alpha)
    PangoCairo.update_layout(ctx, layout)
    PangoCairo.show_layout(ctx, layout)


def _editorial_css(light: bool) -> bytes:
    desk_factor = "0.95" if light else "0.62"
    thumb_muted = "0.6" if light else "0.72"
    return f"""
@define-color omapdf_desk shade(@theme_bg_color, {desk_factor});

window.omapdf-editor, scrolledwindow.omapdf-thumb-rail, listbox.omapdf-thumbs {{
  background: @omapdf_desk;
}}
scrolledwindow.omapdf-page-canvas {{
  background: @omapdf_desk;
}}

box.omapdf-overlay-toolbar {{
  background-image: linear-gradient(to right,
    alpha(@omapdf_desk, 0), alpha(@omapdf_desk, 0.94) 10px, alpha(@omapdf_desk, 0.94));
  border: none;
  padding: 14px 0;
  margin: 0;
  min-width: 44px;
}}
box.omapdf-overlay-toolbar separator {{
  background: transparent;
  min-height: 14px;
}}
box.omapdf-overlay-toolbar .page-indicator,
box.omapdf-overlay-toolbar .zoom-indicator {{
  font-family: monospace;
  font-size: 10.5px;
  font-weight: normal;
  font-feature-settings: "tnum";
  letter-spacing: 0.02em;
  opacity: 0.62;
}}
button.omapdf-sig-card,
box.omapdf-sig-card {{
  padding: 8px 10px;
  border-radius: 0;
  min-width: 168px;
}}
button.omapdf-sig-card label,
box.omapdf-sig-card label {{
  font-family: monospace;
  font-size: 10.5px;
  opacity: 0.62;
}}
box.omapdf-sig-actions {{
  min-width: 280px;
}}
label.toast-banner {{
  background: @theme_fg_color;
  color: @theme_bg_color;
  font-family: monospace;
  font-size: 10.5px;
  padding: 7px 14px;
  border-radius: 0;
  margin-bottom: 24px;
}}
listbox.omapdf-thumbs row {{
  background: transparent;
  padding: 0;
}}
picture.omapdf-thumb {{
  box-shadow: 0 1px 2px alpha(black, 0.10), 0 1px 3px alpha(black, 0.08);
  outline: 1px solid alpha(currentColor, 0.08);
}}
listbox.omapdf-thumbs row:not(.omapdf-thumb-selected) picture.omapdf-thumb {{
  opacity: {thumb_muted};
}}
listbox.omapdf-thumbs row.omapdf-thumb-selected picture.omapdf-thumb {{
  opacity: 1;
  box-shadow: 0 3px 5px alpha(black, 0.08), 0 1px 1px alpha(black, 0.14);
  outline: none;
}}
listbox.omapdf-thumbs row label {{
  font-family: monospace;
  font-size: 10px;
  opacity: 0.42;
}}
listbox.omapdf-thumbs row.omapdf-thumb-selected label {{
  opacity: 0.9;
}}
listbox.omapdf-thumbs row.omapdf-thumb-inserted label {{
  opacity: 0.62;
}}
""".encode()


def _overlay_rail_css() -> bytes:
    """Editorial rail glyphs — loaded last so HeaderBar/Adwaita never fills tool buttons."""
    return b"""
box.omapdf-overlay-toolbar button,
box.omapdf-overlay-toolbar menubutton > button {
  background: transparent;
  background-image: none;
  border: none;
  box-shadow: none;
  outline: none;
  -gtk-icon-shadow: none;
  border-radius: 0;
}
box.omapdf-overlay-toolbar button.suggested-action,
box.omapdf-overlay-toolbar button.destructive-action,
box.omapdf-overlay-toolbar button.success,
box.omapdf-overlay-toolbar button.flat,
box.omapdf-overlay-toolbar button.toggle {
  background: transparent;
  background-color: transparent;
  background-image: none;
  box-shadow: none;
  border: none;
  color: inherit;
}
box.omapdf-overlay-toolbar button.tool-slim,
box.omapdf-overlay-toolbar menubutton.tool-slim > button {
  min-width: 28px;
  min-height: 28px;
  padding: 0;
  margin: 2px 8px;
  opacity: 0.62;
  transition: opacity 120ms ease;
}
box.omapdf-overlay-toolbar button.tool-slim:hover,
box.omapdf-overlay-toolbar menubutton.tool-slim > button:hover {
  opacity: 1;
  background: transparent;
  background-image: none;
}
box.omapdf-overlay-toolbar button.tool-slim:active,
box.omapdf-overlay-toolbar menubutton.tool-slim > button:active {
  background: alpha(currentColor, 0.08);
  background-image: none;
  border-radius: 3px;
}
box.omapdf-overlay-toolbar button.tool-slim:checked,
box.omapdf-overlay-toolbar menubutton.tool-slim > button:checked {
  opacity: 1;
  background-color: transparent;
  background-image: linear-gradient(currentColor, currentColor);
  background-size: 12px 1.5px;
  background-repeat: no-repeat;
  background-position: 50% calc(100% - 3px);
  box-shadow: none;
}
box.omapdf-overlay-toolbar button.tool-slim:disabled,
box.omapdf-overlay-toolbar menubutton.tool-slim > button:disabled {
  opacity: 0.25;
}
box.omapdf-overlay-toolbar button.tool-icon,
box.omapdf-overlay-toolbar menubutton.tool-icon > button {
  padding: 5px;
  min-width: 28px;
  min-height: 28px;
}
box.omapdf-overlay-toolbar box.omapdf-rail-row {
  margin: 0;
}
box.omapdf-overlay-toolbar box.omapdf-rail-row > button.tool-slim {
  margin: 1px 0;
  min-width: 20px;
  padding: 5px 2px;
}
box.omapdf-overlay-toolbar button.omapdf-ghost {
  background: transparent;
  background-image: none;
  border: 1px solid alpha(currentColor, 0.28);
  color: alpha(currentColor, 0.38);
  border-radius: 0;
  min-width: 36px;
  min-height: 24px;
  font-family: monospace;
  font-size: 10.5px;
  font-weight: 500;
  margin: 2px 8px;
  box-shadow: none;
}
box.omapdf-overlay-toolbar button.omapdf-ink {
  background: @theme_fg_color;
  background-image: none;
  color: @theme_bg_color;
  border: none;
  border-radius: 0;
  min-width: 36px;
  min-height: 24px;
  font-family: monospace;
  font-size: 10.5px;
  font-weight: 500;
  margin: 2px 8px;
  box-shadow: none;
}
"""


WINDOW_CONTROLS_CSS = b"""
headerbar.omapdf-window-controls {
  min-height: 28px;
  padding: 0 4px;
  border: none;
  box-shadow: none;
  background: @theme_bg_color;
}
headerbar.omapdf-window-controls button.titlebutton {
  border-radius: 6px;
  min-width: 26px;
  min-height: 22px;
  margin: 2px;
  padding: 2px 4px;
}
"""


def _signature_surface(path: str) -> cairo.ImageSurface:
    pix = sig_store.rasterize(path)
    return cairo.ImageSurface.create_from_png(io.BytesIO(pix.tobytes("png")))


class Editor:
    def __init__(self, pdf: str, ops_file: str | None):
        self.path = str(Path(pdf).resolve())
        self.doc = pymupdf.open(self.path)
        self.page_no = 0
        self.zoom = 1.0
        self.pending: list[dict] = []
        self.undo_stack: list[list[dict]] = []
        self.redo_stack: list[list[dict]] = []
        self.selected: dict | None = None
        self.tool = "select"
        self.page_surface: cairo.ImageSurface | None = None
        self.sig_name = "default"
        self.sig_surfaces: dict[str, cairo.ImageSurface | None] = {}
        self.live_stroke: list[tuple[float, float]] | None = None
        self.rubber: tuple[float, float, float, float] | None = None
        self.drag_base: tuple[float, float] | None = None
        self.pen_color = PEN_COLORS[1][1]
        self.shape_kind = "rect"
        self.zoom_pct: float | None = None  # None = fit page in viewport
        self.pinch_live_scale = 1.0  # cairo extra scale while pinching
        self.pinch_focus_area: tuple[float, float] | None = None
        self.page_origin = (0.0, 0.0)  # paper top-left in view pixels
        self.paper_px = (0, 0)  # paper width/height in view pixels
        self.search_term = ""
        self.search_hits: list[tuple[int, pymupdf.Rect]] = []
        self.search_pos = -1
        self.page_preview = PagePreviewState(self.path)
        self.window: Gtk.Window | None = None
        self._view_doc: pymupdf.Document | None = None
        self.redact_free_rect = False
        self.redact_save_as_copy = True
        self.redact_modal_shown = False
        if ops_file:
            self._load_proposals(ops_file)

    # ---- model ----------------------------------------------------------

    def invalidate_view(self):
        if self._view_doc is not None:
            self._view_doc.close()
            self._view_doc = None

    def viewing_doc(self) -> pymupdf.Document:
        if self._view_doc is None:
            self._view_doc = self.page_preview.open_view()
        return self._view_doc

    def page_doc(self) -> pymupdf.Document:
        """Scratch PDF when page ops are pending; otherwise the live file handle."""
        if self.page_preview.has_changes():
            return self.viewing_doc()
        return self.doc

    def page(self) -> pymupdf.Page:
        return self.page_doc()[self.page_no]

    def page_count(self) -> int:
        return self.page_doc().page_count

    def checkpoint(self):
        self.undo_stack.append({
            "kind": "pending",
            "pending": copy.deepcopy(self.pending),
            "page_ops": copy.deepcopy(self.page_preview.page_ops),
        })
        self.redo_stack.clear()

    def record_save(self, file_before: bytes, pending_before: list[dict], page_ops_before: list[dict]):
        """A save is an undoable step too: undoing it reverts the file and
        resurrects the saved items as editable ghosts."""
        self.undo_stack.append({
            "kind": "save",
            "file_before": file_before,
            "file_after": Path(self.path).read_bytes(),
            "pending_before": pending_before,
            "page_ops_before": page_ops_before,
        })
        self.redo_stack.clear()

    def _restore_file(self, data: bytes):
        self.doc.close()
        Path(self.path).write_bytes(data)
        self.doc = pymupdf.open(self.path)
        self.invalidate_view()

    def undo(self) -> bool:
        """Returns True when the file itself changed (a save was reverted)."""
        if not self.undo_stack:
            return False
        entry = self.undo_stack.pop()
        if entry["kind"] == "pending":
            self.redo_stack.append({
                "kind": "pending",
                "pending": self.pending,
                "page_ops": copy.deepcopy(self.page_preview.page_ops),
            })
            self.pending = entry["pending"]
            self.page_preview.page_ops = copy.deepcopy(entry.get("page_ops", []))
            self.page_preview.rebuild()
            self.invalidate_view()
            self.selected = None
            return False
        self.redo_stack.append(entry)
        self._restore_file(entry["file_before"])
        self.pending = copy.deepcopy(entry["pending_before"])
        self.page_preview.page_ops = copy.deepcopy(entry.get("page_ops_before", []))
        self.page_preview.rebuild()
        self.invalidate_view()
        self.selected = None
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        entry = self.redo_stack.pop()
        if entry["kind"] == "pending":
            self.undo_stack.append({
                "kind": "pending",
                "pending": self.pending,
                "page_ops": copy.deepcopy(self.page_preview.page_ops),
            })
            self.pending = entry["pending"]
            self.page_preview.page_ops = copy.deepcopy(entry.get("page_ops", []))
            self.page_preview.rebuild()
            self.invalidate_view()
            self.selected = None
            return False
        self.undo_stack.append(entry)
        self._restore_file(entry["file_after"])
        self.pending = []
        self.page_preview.clear()
        self.page_preview.rebuild()
        self.invalidate_view()
        self.selected = None
        return True

    def sig_aspect(self, name: str | None = None) -> float:
        surface = self._ensure_sig(name)
        return surface.get_height() / surface.get_width() if surface else 0.4

    def _ensure_sig(self, name: str | None = None):
        name = name or self.sig_name
        if name not in self.sig_surfaces:
            try:
                self.sig_surfaces[name] = _signature_surface(str(sig_store.get(name)))
            except FileNotFoundError:
                self.sig_surfaces[name] = None
        return self.sig_surfaces[name]

    def invalidate_sigs(self) -> None:
        self.sig_surfaces.clear()

    def _load_proposals(self, ops_file: str):
        payload = json.loads(Path(ops_file).read_text())
        for op in payload:
            kind = op.get("op")
            page = op.get("page", 1) - 1
            if kind == "place_signature":
                w = float(op.get("width", 180))
                name = op.get("signature", "default")
                self.pending.append({
                    "kind": "sig", "page": page, "x": op["at"][0], "y": op["at"][1],
                    "w": w, "h": w * self.sig_aspect(name), "date": bool(op.get("date")),
                    "signature": name,
                })
            elif kind == "text_box":
                r = op["rect"]
                self.pending.append({
                    "kind": "text", "page": page, "x": r[0], "y": r[1],
                    "text": op["text"], "size": float(op.get("size", 11)),
                })
            elif kind == "highlight" and "rect" in op:
                r = op["rect"]
                self.pending.append({
                    "kind": "highlight", "page": page,
                    "x0": r[0], "y0": r[1], "x1": r[2], "y1": r[3],
                })
            elif kind == "note":
                self.pending.append({
                    "kind": "note", "page": page,
                    "x": op["at"][0], "y": op["at"][1], "text": op["text"],
                })
            elif kind == "ink":
                self.pending.append({
                    "kind": "ink", "page": page, "strokes": op["strokes"],
                    "color": op.get("color", [0.75, 0.1, 0.1]),
                    "width": op.get("width", PEN_WIDTH),
                })
            elif kind == "shape":
                shape = op["shape"]
                if shape in ("line", "arrow"):
                    item = {
                        "kind": "shape", "page": page, "shape": shape,
                        "x0": op["from"][0], "y0": op["from"][1],
                        "x1": op["to"][0], "y1": op["to"][1],
                        "color": op.get("color", [0.1, 0.1, 0.1]),
                        "width": op.get("width", PEN_WIDTH),
                    }
                else:
                    r = op["rect"]
                    item = {
                        "kind": "shape", "page": page, "shape": shape,
                        "x0": r[0], "y0": r[1], "x1": r[2], "y1": r[3],
                        "color": op.get("color", [0.1, 0.1, 0.1]),
                        "width": op.get("width", PEN_WIDTH),
                    }
                self.pending.append(item)
            elif kind == "redact":
                if "rect" in op:
                    r = op["rect"]
                    item = {
                        "kind": "redact", "page": page,
                        "x0": r[0], "y0": r[1], "x1": r[2], "y1": r[3],
                    }
                else:
                    rects = self.doc[page].search_for(op["match"])
                    if not rects:
                        continue
                    r = rects[0]
                    item = {
                        "kind": "redact", "page": page,
                        "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1,
                        "match": op["match"],
                    }
                self.pending.append(item)
        if self.pending:
            self.selected = self.pending[0]
            self.page_no = self.pending[0]["page"]

    def to_ops(self) -> list[dict]:
        ops = []
        for it in self.pending:
            page = it["page"] + 1
            if it["kind"] == "sig":
                ops.append({"op": "place_signature", "page": page,
                            "at": [it["x"], it["y"]], "width": it["w"],
                            "signature": it.get("signature", "default"),
                            "date": it.get("date", False)})
            elif it["kind"] == "text":
                w = max(40.0, len(it["text"]) * it["size"] * 0.6)
                ops.append({"op": "text_box", "page": page, "text": it["text"],
                            "rect": [it["x"], it["y"], it["x"] + w, it["y"] + it["size"] * 1.6],
                            "size": it["size"]})
            elif it["kind"] == "note":
                ops.append({"op": "note", "page": page,
                            "at": [it["x"], it["y"]], "text": it["text"]})
            elif it["kind"] == "highlight":
                ops.append({"op": "highlight", "page": page,
                            "rect": [min(it["x0"], it["x1"]), min(it["y0"], it["y1"]),
                                     max(it["x0"], it["x1"]), max(it["y0"], it["y1"])]})
            elif it["kind"] == "ink":
                ops.append({"op": "ink", "page": page, "strokes": it["strokes"],
                            "color": it["color"], "width": it["width"]})
            elif it["kind"] == "shape":
                base = {
                    "op": "shape",
                    "page": page,
                    "shape": it["shape"],
                    "color": it["color"],
                    "width": it["width"],
                }
                if it["shape"] in ("line", "arrow"):
                    ops.append({**base, "from": [it["x0"], it["y0"]], "to": [it["x1"], it["y1"]]})
                else:
                    x0, y0, x1, y1 = _norm_rect(it)
                    ops.append({**base, "rect": [x0, y0, x1, y1]})
            elif it["kind"] == "redact":
                if it.get("match"):
                    ops.append({"op": "redact", "page": page,
                                "match": it["match"], "fill": [0, 0, 0]})
                else:
                    x0, y0, x1, y1 = _norm_rect(it)
                    ops.append({"op": "redact", "page": page,
                                "rect": [x0, y0, x1, y1], "fill": [0, 0, 0]})
            elif it["kind"] == "field_fill":
                ops.append({"op": "fill_field", "field": it["field"], "value": it["value"]})
            elif it["kind"] == "delete_annot":
                ops.append({"op": "delete_annotation", "page": page, "index": it["index"]})
        return engine._order_ops(ops)

    # ---- geometry -------------------------------------------------------

    def item_rect(self, it) -> tuple[float, float, float, float]:
        if it["kind"] == "sig":
            return it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"]
        if it["kind"] == "text":
            w = max(40.0, len(it["text"]) * it["size"] * 0.6)
            return it["x"], it["y"], it["x"] + w, it["y"] + it["size"] * 1.6
        if it["kind"] == "note":
            return it["x"], it["y"], it["x"] + NOTE_SIZE, it["y"] + NOTE_SIZE
        if it["kind"] == "highlight":
            return _norm_rect(it)
        if it["kind"] == "shape":
            return _norm_rect(it)
        if it["kind"] == "redact":
            return _norm_rect(it)
        if it["kind"] == "field_fill":
            r = it["rect"]
            return r[0], r[1], r[2], r[3]
        if it["kind"] == "delete_annot":
            r = it["rect"]
            return r[0], r[1], r[2], r[3]
        xs = [p[0] for s in it["strokes"] for p in s]
        ys = [p[1] for s in it["strokes"] for p in s]
        return min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4

    def hit(self, x, y):
        for it in reversed([p for p in self.pending if p["page"] == self.page_no]):
            x0, y0, x1, y1 = self.item_rect(it)
            if x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4:
                return it
        return None

    def hit_widget(self, x, y):
        """Return an empty AcroForm text widget at (x, y), if any."""
        point = pymupdf.Point(x, y)
        for widget in self.page().widgets():
            if not widget.field_name or not widget.rect.contains(point):
                continue
            if widget.field_type != pymupdf.PDF_WIDGET_TYPE_TEXT:
                continue
            if (widget.field_value or "").strip():
                continue
            return widget
        return None

    def hit_saved_annot(self, x, y):
        """Return the smallest saved annotation under (x, y), if any."""
        best = None
        for index, annot in enumerate(self.page().annots() or []):
            if self._annot_marked_deleted(self.page_no, index):
                continue
            rect = annot.rect
            pad = 4
            if rect.x0 - pad <= x <= rect.x1 + pad and rect.y0 - pad <= y <= rect.y1 + pad:
                area = max(1.0, rect.width * rect.height)
                if best is None or area < best["area"]:
                    best = {
                        "kind": "saved_annot",
                        "page": self.page_no,
                        "index": index,
                        "annot_type": annot.type[1],
                        "rect": list(rect),
                        "area": area,
                    }
        return best

    def _annot_marked_deleted(self, page_no: int, index: int) -> bool:
        for it in self.pending:
            if it.get("kind") == "delete_annot" and it["page"] == page_no and it["index"] == index:
                return True
        return False

    def move_item(self, it, dx, dy):
        if it["kind"] in ("sig", "text", "note"):
            it["x"] += dx
            it["y"] += dy
        elif it["kind"] in ("highlight", "redact", "shape"):
            for k in ("x0", "x1"):
                it[k] += dx
            for k in ("y0", "y1"):
                it[k] += dy
        else:
            it["strokes"] = [[(px + dx, py + dy) for px, py in s] for s in it["strokes"]]


def run(pdf: str, ops_file: str | None = None) -> int:
    _sync_color_scheme()
    ed = Editor(pdf, ops_file)
    app = Gtk.Application(
        application_id="org.omepreview.Editor", flags=Gio.ApplicationFlags.NON_UNIQUE
    )

    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app)
        win.set_default_size(980, 900)
        show_window_controls = window_controls_enabled()
        if show_window_controls:
            win.add_css_class("omapdf-window-controls-on")
        else:
            win.set_decorated(False)
        win.add_css_class("omapdf-editor")
        ed.window = win
        chrome = {
            "desk": (0.92, 0.91, 0.91),
            "fg": (0.18, 0.2, 0.21),
            "light": True,
            "shadows": SHADOWS_LIGHT,
        }

        area = Gtk.DrawingArea()
        area.set_can_target(True)
        sidebar_api = {
            "refresh": lambda: None,
            "highlight_current": lambda _n: None,
            "select_row": lambda _n: None,
            "sidebar_focus": {"active": False},
            "selected_1based": lambda: [],
            "has_page_selection": lambda: False,
            "delete_selected_pages": lambda: None,
            "rotate_selected": lambda _d: None,
            "insert_blank_after_current": lambda: None,
            "copy_selected_pages": lambda: False,
            "paste_pages": lambda: False,
            "cut_selected_pages": lambda: False,
        }

        save_style_hook = {"fn": lambda: None}

        def refresh_title():
            dirty = ed.pending or ed.page_preview.has_changes()
            dot = " •" if dirty else ""
            win.set_title(f"{Path(ed.path).name}{dot} — omepreview")
            save_style_hook["fn"]()

        def viewport_width() -> float:
            # Prefer the scroller's allocated width — hadjustment page-size can
            # report the content width or 0 before the first layout pass.
            avail = float(scroller.get_width() or 0)
            if avail < 50:
                avail = float(scroller.get_allocated_width())
            if avail < 50:
                avail = float(scroller.get_hadjustment().get_page_size())
            if avail < 50:
                avail = 900.0
            return avail

        def viewport_height() -> float:
            avail = float(scroller.get_height() or 0)
            if avail < 50:
                avail = float(scroller.get_allocated_height())
            if avail < 50:
                avail = float(scroller.get_vadjustment().get_page_size())
            if avail < 50:
                avail = 700.0
            return avail

        def fit_page_zoom() -> float:
            page = ed.page()
            pw = page.rect.width or 595.0
            ph = page.rect.height or 842.0
            margin = PAGE_MARGIN_PX * 2
            zw = (viewport_width() - margin) / pw
            zh = (viewport_height() - margin) / ph
            return max(0.05, min(zw, zh))

        def to_page_point(cx: float, cy: float) -> tuple[float, float]:
            ox, oy = ed.page_origin
            return ((cx - ox) / ed.zoom, (cy - oy) / ed.zoom)

        def to_view_point(px: float, py: float) -> tuple[float, float]:
            ox, oy = ed.page_origin
            return (ox + px * ed.zoom, oy + py * ed.zoom)

        def capture_v_anchor(viewport_y: float | None = None) -> dict:
            vadj = scroller.get_vadjustment()
            vh = float(vadj.get_page_size() or scroller.get_height() or 1.0)
            if viewport_y is None:
                viewport_y = vh / 2.0
            return {
                "page_y": page_y_at_focus(
                    page_origin_y=ed.page_origin[1],
                    zoom=ed.zoom,
                    vscroll=float(vadj.get_value()),
                    viewport_y=float(viewport_y),
                ),
                "viewport_y": float(viewport_y),
            }

        def restore_v_anchor(anchor: dict | None) -> None:
            if not anchor:
                return
            vadj = scroller.get_vadjustment()
            vmax = max(0.0, float(vadj.get_upper() - vadj.get_page_size()))
            vadj.set_value(
                scroll_to_keep_focus(
                    page_origin_y=ed.page_origin[1],
                    zoom=ed.zoom,
                    page_y=anchor["page_y"],
                    viewport_y=anchor["viewport_y"],
                    vmax=vmax,
                )
            )

        sig_drag = {"active": False, "dragging": False, "just_dropped": False}
        pinch_state = {
            "start_pct": None,
            "live_pct": None,
            "commit_id": 0,
            "anchor": None,
            "pending_commit": False,
            "deferred_render": False,
            "deferred_anchor": None,
        }

        def render_page(*, v_anchor: dict | None = None):
            # Resizing the drawing area during a live signature-popover drag
            # can unrealize the popover; GTK then SIGSEGVs on set_autohide.
            if sig_drag.get("active"):
                pinch_state["deferred_render"] = True
                if v_anchor is not None:
                    pinch_state["deferred_anchor"] = v_anchor
                return
            ed.pinch_live_scale = 1.0
            ed.pinch_focus_area = None
            if ed.zoom_pct is None:
                z = fit_page_zoom()
            else:
                z = max(0.05, ed.zoom_pct / 100 * (96 / 72))
            ed.zoom = z
            zoom_dot.set_text("Fit" if ed.zoom_pct is None else f"{int(ed.zoom_pct)}%")
            page = ed.page()
            matrix = pymupdf.Matrix(z, z).prerotate(page.rotation)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            if pix.width < 1 or pix.height < 1:
                return
            ed.page_surface = cairo.ImageSurface.create_from_png(
                io.BytesIO(pix.tobytes("png"))
            )
            paper_w, paper_h = pix.width, pix.height
            ed.paper_px = (paper_w, paper_h)
            view_w = viewport_width()
            view_h = viewport_height()
            content_w = max(view_w, paper_w + 2 * PAGE_MARGIN_PX)
            content_h = max(view_h, paper_h + 2 * PAGE_MARGIN_PX)
            page_x = (content_w - paper_w) / 2
            page_y = (content_h - paper_h) / 2
            ed.page_origin = (page_x, page_y)
            area.set_content_width(int(content_w))
            area.set_content_height(int(content_h))
            page_label.set_text(f"{ed.page_no + 1} / {ed.page_count()}")
            update_nav()
            sidebar_api["highlight_current"](ed.page_no)
            if v_anchor is not None:
                restore_v_anchor(v_anchor)
                GLib.idle_add(lambda: (restore_v_anchor(v_anchor), False)[1])
            area.queue_draw()
            refresh_title()

        # -- drawing ------------------------------------------------------

        def draw(_a, ctx, w, h):
            ctx.save()
            desk = chrome["desk"]
            fg = chrome["fg"]
            ctx.set_source_rgb(*desk)
            ctx.rectangle(0, 0, w, h)
            ctx.fill()
            ox, oy = ed.page_origin
            pw, ph = ed.paper_px
            if pw > 0 and ph > 0:
                folio = f"{Path(ed.path).name} · {ed.page_count()} pages"
                _draw_folio(ctx, folio, ox, oy - 13, fg, 0.5)
                live = ed.pinch_live_scale
                if live != 1.0:
                    if ed.pinch_focus_area is not None:
                        fx, fy = ed.pinch_focus_area
                    else:
                        fx = ox + pw / 2
                        fy = oy + ph / 2
                    ctx.translate(fx, fy)
                    ctx.scale(live, live)
                    ctx.translate(-fx, -fy)
                _draw_paper_shadow(ctx, ox, oy, pw, ph, chrome["shadows"])
                ctx.set_source_rgb(1, 1, 1)
                ctx.rectangle(ox, oy, pw, ph)
                ctx.fill()
                if ed.page_surface:
                    ctx.set_source_surface(ed.page_surface, ox, oy)
                    ctx.paint()
                if chrome["light"]:
                    ctx.set_source_rgba(fg[0], fg[1], fg[2], PAPER_EDGE_ALPHA)
                    ctx.set_line_width(1.0)
                    ctx.rectangle(ox, oy, pw, ph)
                    ctx.stroke()
            ctx.translate(ox, oy)
            ctx.scale(ed.zoom, ed.zoom)
            for it in ed.pending:
                if it["page"] == ed.page_no:
                    draw_item(ctx, it)
            if (
                ed.selected
                and ed.selected.get("kind") == "saved_annot"
                and ed.selected["page"] == ed.page_no
            ):
                x0, y0, x1, y1 = ed.selected["rect"]
                w, h = x1 - x0 + 8, y1 - y0 + 8
                ctx.set_source_rgba(*SELECT_COLOR, 0.10)
                ctx.rectangle(x0 - 4, y0 - 4, w, h)
                ctx.fill()
                ctx.set_source_rgba(*SELECT_COLOR, 0.95)
                ctx.set_line_width(1.6)
                ctx.rectangle(x0 - 4, y0 - 4, w, h)
                ctx.stroke()
            if ed.live_stroke and len(ed.live_stroke) > 1:
                _stroke_path(ctx, [ed.live_stroke], ed.pen_color, PEN_WIDTH)
            if ed.rubber:
                x0, y0, x1, y1 = ed.rubber
                if ed.tool == "crop":
                    rx0, ry0, rx1, ry1 = (
                        min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1),
                    )
                    pw, ph = ed.page().rect.width, ed.page().rect.height
                    ctx.set_source_rgba(0, 0, 0, 0.42)
                    for band in (
                        (0, 0, pw, ry0),
                        (0, ry1, pw, ph - ry1),
                        (0, ry0, rx0, ry1 - ry0),
                        (rx1, ry0, pw - rx1, ry1 - ry0),
                    ):
                        bx, by, bw, bh = band
                        if bw > 0 and bh > 0:
                            ctx.rectangle(bx, by, bw, bh)
                            ctx.fill()
                    ctx.set_source_rgba(0.2, 0.55, 0.95, 0.95)
                    ctx.set_line_width(1.6)
                    ctx.set_dash([6, 4])
                    ctx.rectangle(rx0, ry0, rx1 - rx0, ry1 - ry0)
                    ctx.stroke()
                    ctx.set_dash([])
                elif ed.tool == "shape":
                    _draw_shape(
                        ctx, ed.shape_kind, x0, y0, x1, y1,
                        ed.pen_color, PEN_WIDTH, alpha=0.85,
                    )
                elif ed.tool == "redact":
                    ctx.set_source_rgba(0, 0, 0, 0.35)
                    ctx.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
                    ctx.fill()
                else:
                    ctx.set_source_rgba(1, 0.85, 0.1, 0.35)
                    ctx.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
                    ctx.fill()
            for i, (pno, rect) in enumerate(ed.search_hits):
                if pno != ed.page_no:
                    continue
                current = i == ed.search_pos
                ctx.set_source_rgba(1, 0.55, 0.05, 0.45 if current else 0.22)
                ctx.rectangle(rect.x0 - 1, rect.y0 - 1, rect.width + 2, rect.height + 2)
                ctx.fill()
                if current:
                    ctx.set_source_rgba(0.9, 0.4, 0, 0.9)
                    ctx.set_line_width(1.4)
                    ctx.rectangle(rect.x0 - 1, rect.y0 - 1, rect.width + 2, rect.height + 2)
                    ctx.stroke()
            ctx.restore()

        def draw_item(ctx, it):
            if it["kind"] == "sig":
                surface = ed._ensure_sig(it.get("signature") or ed.sig_name)
                if surface:
                    ctx.save()
                    ctx.translate(it["x"], it["y"])
                    s = it["w"] / surface.get_width()
                    ctx.scale(s, s)
                    ctx.set_source_surface(surface, 0, 0)
                    ctx.paint_with_alpha(0.92)
                    ctx.restore()
            elif it["kind"] == "text":
                ctx.set_source_rgb(0.05, 0.05, 0.05)
                ctx.select_font_face("sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                ctx.set_font_size(it["size"])
                ctx.move_to(it["x"], it["y"] + it["size"])
                ctx.show_text(it["text"])
            elif it["kind"] == "note":
                x, y = it["x"], it["y"]
                s = NOTE_SIZE
                fold = s * 0.3
                # Yellow sticky with a folded corner and text lines.
                ctx.move_to(x, y)
                ctx.line_to(x + s, y)
                ctx.line_to(x + s, y + s - fold)
                ctx.line_to(x + s - fold, y + s)
                ctx.line_to(x, y + s)
                ctx.close_path()
                ctx.set_source_rgb(1.0, 0.87, 0.35)
                ctx.fill_preserve()
                ctx.set_source_rgb(0.7, 0.58, 0.1)
                ctx.set_line_width(0.8)
                ctx.stroke()
                ctx.move_to(x + s - fold, y + s)
                ctx.line_to(x + s - fold, y + s - fold)
                ctx.line_to(x + s, y + s - fold)
                ctx.stroke()
                ctx.set_source_rgb(0.55, 0.45, 0.08)
                for i in (0.3, 0.5, 0.7):
                    ctx.move_to(x + s * 0.15, y + s * i)
                    ctx.line_to(x + s * 0.72, y + s * i)
                    ctx.stroke()
            elif it["kind"] == "highlight":
                x0, y0, x1, y1 = ed.item_rect(it)
                ctx.set_source_rgba(1, 0.85, 0.1, 0.35)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.fill()
            elif it["kind"] == "shape":
                _draw_shape(
                    ctx, it["shape"], it["x0"], it["y0"], it["x1"], it["y1"],
                    tuple(it["color"]), it["width"], alpha=0.92,
                )
            elif it["kind"] == "redact":
                x0, y0, x1, y1 = ed.item_rect(it)
                ctx.set_source_rgba(0, 0, 0, 0.45)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.fill()
                ctx.set_source_rgba(0.9, 0.2, 0.2, 0.85)
                ctx.set_line_width(1.2)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.stroke()
            elif it["kind"] == "field_fill":
                x0, y0, x1, y1 = ed.item_rect(it)
                ctx.set_source_rgba(0.2, 0.45, 0.95, 0.12)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.fill()
                ctx.set_source_rgba(0.15, 0.45, 0.95, 0.9)
                ctx.set_line_width(1.2)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.stroke()
                ctx.set_source_rgb(0.05, 0.05, 0.05)
                ctx.select_font_face("sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                size = min(12.0, max(9.0, (y1 - y0) * 0.7))
                ctx.set_font_size(size)
                ctx.move_to(x0 + 3, y0 + size + 1)
                ctx.show_text(it["value"])
            elif it["kind"] == "delete_annot":
                x0, y0, x1, y1 = ed.item_rect(it)
                ctx.set_source_rgba(0.9, 0.15, 0.15, 0.22)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.fill()
                ctx.set_source_rgba(0.9, 0.15, 0.15, 0.9)
                ctx.set_line_width(1.4)
                ctx.set_dash([4, 3])
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.stroke()
                ctx.set_dash([])
            else:
                _stroke_path(ctx, it["strokes"], it["color"], it["width"])
            selected = ed.selected if ed.selected in ed.pending else None
            if it is selected:
                x0, y0, x1, y1 = ed.item_rect(it)
                w, h = x1 - x0 + 8, y1 - y0 + 8
                # Tinted fill + solid border + corner handles: unmistakable.
                ctx.set_source_rgba(*SELECT_COLOR, 0.10)
                ctx.rectangle(x0 - 4, y0 - 4, w, h)
                ctx.fill()
                ctx.set_source_rgba(*SELECT_COLOR, 0.95)
                ctx.set_line_width(1.6)
                ctx.rectangle(x0 - 4, y0 - 4, w, h)
                ctx.stroke()
                hs = 3.2
                for hx in (x0 - 4, x0 - 4 + w):
                    for hy in (y0 - 4, y0 - 4 + h):
                        ctx.set_source_rgb(1, 1, 1)
                        ctx.rectangle(hx - hs, hy - hs, hs * 2, hs * 2)
                        ctx.fill_preserve()
                        ctx.set_source_rgba(*SELECT_COLOR, 0.95)
                        ctx.set_line_width(1.1)
                        ctx.stroke()

        def _stroke_path(ctx, strokes, color, width):
            ctx.set_source_rgb(*color)
            ctx.set_line_width(width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            for s in strokes:
                if len(s) < 2:
                    continue
                ctx.move_to(*s[0])
                for p in s[1:]:
                    ctx.line_to(*p)
                ctx.stroke()

        area.set_draw_func(draw)

        # -- text entry popover -------------------------------------------

        def prompt_entry(px, py, placeholder, on_text, initial=""):
            pop = Gtk.Popover()
            pop.set_parent(area)
            rect = Gdk.Rectangle()
            vx, vy = to_view_point(px, py)
            rect.x, rect.y, rect.width, rect.height = int(vx), int(vy), 1, 1
            pop.set_pointing_to(rect)
            entry = Gtk.Entry()
            entry.set_placeholder_text(placeholder)
            entry.set_width_chars(30)
            entry.set_text(initial)
            pop.set_child(entry)

            def commit(_e):
                text = entry.get_text().strip()
                pop.popdown()
                if text:
                    ed.checkpoint()
                    item = on_text(text)
                    if not any(p is item for p in ed.pending):
                        ed.pending.append(item)
                    ed.selected = item
                    area.queue_draw()
                    refresh_title()

            entry.connect("activate", commit)
            pop.popup()
            entry.grab_focus()

        def prompt_text(px, py):
            prompt_entry(px, py, "Type text, then Enter", lambda t: {
                "kind": "text", "page": ed.page_no, "x": px, "y": py,
                "text": t, "size": 12.0,
            })

        def prompt_note(px, py):
            prompt_entry(px, py, "Sticky note comment, then Enter", lambda t: {
                "kind": "note", "page": ed.page_no, "x": px, "y": py, "text": t,
            })

        def prompt_field_fill(widget, px, py):
            name = widget.field_name

            def commit(value):
                ed.checkpoint()
                item = {
                    "kind": "field_fill",
                    "page": ed.page_no,
                    "field": name,
                    "value": value,
                    "rect": list(widget.rect),
                }
                ed.pending.append(item)
                ed.selected = item
                toast(f"Field {name!r} — not applied until Save")
                return item

            prompt_entry(px, py, f"Fill {name}, then Enter", commit)

        def edit_pending(item):
            """Re-open a pending note/text for editing, pre-filled."""

            def apply_text(t):
                item["text"] = t
                return item

            label = "Edit note — Enter to update" if item["kind"] == "note" \
                else "Edit text — Enter to update"
            prompt_entry(item["x"], item["y"], label, apply_text,
                         initial=item["text"])

        def show_saved_annot(px, py):
            """Click on an already-saved annotation: pop open its content."""
            best = None
            # Copy plain values inside the loop: PyMuPDF annot objects can go
            # stale once the generator advances.
            for a in ed.page().annots() or []:
                r = a.rect
                pad = 6
                if r.x0 - pad <= px <= r.x1 + pad and r.y0 - pad <= py <= r.y1 + pad:
                    area_sz = max(1.0, r.width * r.height)
                    if best is None or area_sz < best[2]:
                        best = (a.type[1], (a.info.get("content") or "").strip(), area_sz)
            # Clickability means "there is a comment to read": annotations
            # without text (bare highlights, ink) don't pop anything.
            if best is None or not best[1]:
                return False
            kind, content, _ = best
            titles = {"Text": "Comment", "FreeText": "Text box",
                      "Highlight": "Highlight comment"}
            pop = Gtk.Popover()
            pop.set_parent(area)
            rect = Gdk.Rectangle()
            vx, vy = to_view_point(px, py)
            rect.x, rect.y, rect.width, rect.height = int(vx), int(vy), 1, 1
            pop.set_pointing_to(rect)
            # Near the right edge, open leftward so the popover stays over
            # the page instead of spilling into the sidebar/window edge.
            if px > ed.page().rect.width * 0.72:
                pop.set_position(Gtk.PositionType.LEFT)
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vbox.set_margin_top(8)
            vbox.set_margin_bottom(8)
            vbox.set_margin_start(10)
            vbox.set_margin_end(10)
            title = Gtk.Label()
            title.set_markup(f"<b>{GLib.markup_escape_text(titles.get(kind, kind))}</b>")
            title.set_halign(Gtk.Align.START)
            vbox.append(title)
            body = Gtk.Label(label=content)
            body.set_wrap(True)
            body.set_max_width_chars(44)
            body.set_halign(Gtk.Align.START)
            vbox.append(body)
            pop.set_child(vbox)
            # Defer past the in-flight click gesture: popping up during the
            # press can get the popover dismissed by its own click's release.
            GLib.idle_add(lambda: (pop.popup(), False)[1])
            return True

        # -- input --------------------------------------------------------

        def add_stamp(strokes_template, color, px, py):
            ed.checkpoint()
            scale = STAMP_SIZE / 14.0
            strokes = [[(px + sx * scale, py + sy * scale) for sx, sy in s]
                       for s in strokes_template]
            item = {"kind": "ink", "page": ed.page_no, "strokes": strokes,
                    "color": list(color), "width": 2.4}
            ed.pending.append(item)
            ed.selected = item
            set_tool("select")

        sig_ui = {"rebuild": lambda: None}

        def next_sig_name() -> str:
            names = set(sig_store.list_names())
            if "default" not in names:
                return "default"
            n = 2
            while f"signature-{n}" in names:
                n += 1
            return f"signature-{n}"

        def record_signature(name: str) -> bool:
            import subprocess

            toast("Record your signature on the trackpad…")
            proc = subprocess.run(
                [sys.executable, "-m", "omepreview.cli", "sig", "draw", "--name", name],
                env=os.environ.copy(),
            )
            ed.invalidate_sigs()
            if proc.returncode != 0:
                toast("Signature capture cancelled")
                return False
            ed.sig_name = name
            toast(f"Saved {name!r} — drag it onto the page")
            sig_ui["rebuild"]()
            return True

        def place_named_signature(name: str, px: float, py: float) -> bool:
            ed.sig_name = name
            if ed._ensure_sig(name) is None:
                return False
            ed.checkpoint()
            item = signature_ghost(
                ed.page_no, name, px, py, ed.sig_aspect(name),
            )
            ed.pending.append(item)
            ed.selected = item
            set_tool("select")
            area.queue_draw()
            refresh_title()
            return True

        click = Gtk.GestureClick()

        def on_click(_g, n_press, cx, cy):
            px, py = to_page_point(cx, cy)
            hit_item = ed.hit(px, py)
            if ed.tool == "text":
                if hit_item and hit_item["kind"] == "text":
                    edit_pending(hit_item)
                else:
                    prompt_text(px, py)
            elif ed.tool == "note":
                if hit_item and hit_item["kind"] == "note":
                    edit_pending(hit_item)
                else:
                    prompt_note(px, py)
            elif ed.tool == "sign":
                if sig_drag["active"] or sig_drag["just_dropped"]:
                    return
                name = ed.sig_name
                if ed._ensure_sig(name) is None:
                    names = sig_store.list_names()
                    if names:
                        name = names[0]
                        ed.sig_name = name
                    else:
                        name = "default"
                        if not record_signature(name):
                            return
                place_named_signature(name, px, py)
            elif ed.tool == "check":
                add_stamp(CHECK, CHECK_COLOR, px, py)
            elif ed.tool == "cross":
                add_stamp(CROSS, CROSS_COLOR, px, py)
            else:
                if hit_item:
                    ed.selected = hit_item
                else:
                    widget = ed.hit_widget(px, py)
                    if widget is not None:
                        prompt_field_fill(widget, px, py)
                    else:
                        saved = ed.hit_saved_annot(px, py)
                        if saved:
                            ed.selected = saved
                        else:
                            ed.selected = None
                            try:
                                show_saved_annot(px, py)
                            except Exception as exc:
                                toast(f"Couldn't open annotation: {exc}")
                if ed.selected and ed.selected in ed.pending and n_press >= 2 and ed.selected["kind"] in ("note", "text"):
                    edit_pending(ed.selected)
            area.queue_draw()
            refresh_title()

        click.connect("pressed", on_click)
        area.add_controller(click)

        def _pointer_in_widget(widget):
            """Pointer position in *widget* coordinates, or None."""
            native = widget.get_native()
            if native is None:
                return None
            surface = native.get_surface()
            if surface is None:
                return None
            display = widget.get_display()
            seat = display.get_default_seat() if display is not None else None
            device = seat.get_pointer() if seat is not None else None
            if device is None:
                return None
            ok, sx, sy, _mask = surface.get_device_position(device)
            if not ok:
                return None
            src = native if isinstance(native, Gtk.Widget) else win
            try:
                from gi.repository import Graphene

                ok, pt = src.compute_point(widget, Graphene.Point().init(sx, sy))
                if ok:
                    return float(pt.x), float(pt.y)
            except (TypeError, ValueError):
                pass
            try:
                mapped = src.translate_coordinates(widget, sx, sy)
            except Exception:
                return None
            return mapped_point(mapped)

        # Hovering a note/text (pending or saved) previews its content.
        area.set_has_tooltip(True)

        def on_tooltip(_w, tx, ty, _kb, tooltip):
            px, py = to_page_point(tx, ty)
            it = ed.hit(px, py)
            if it and it.get("kind") in ("note", "text") and it.get("text"):
                tooltip.set_text(it["text"])
                return True
            try:
                for a in ed.page().annots() or []:
                    r = a.rect
                    if r.x0 - 4 <= px <= r.x1 + 4 and r.y0 - 4 <= py <= r.y1 + 4:
                        content = (a.info.get("content") or "").strip()
                        if content:
                            tooltip.set_text(content)
                            return True
            except Exception:
                pass
            return False

        area.connect("query-tooltip", on_tooltip)

        drag = Gtk.GestureDrag()

        def on_drag_begin(g, sx, sy):
            if sig_drag["active"] or sig_drag["just_dropped"]:
                g.set_state(Gtk.EventSequenceState.DENIED)
                return
            px, py = to_page_point(sx, sy)
            if ed.tool == "pen":
                ed.live_stroke = [(px, py)]
            elif ed.tool == "highlight":
                ed.rubber = (px, py, px, py)
            elif ed.tool == "shape":
                ed.rubber = (px, py, px, py)
            elif ed.tool == "crop":
                ed.rubber = (px, py, px, py)
            elif ed.tool == "redact":
                ed.rubber = (px, py, px, py)
            elif ed.tool == "select":
                hit_item = ed.hit(px, py)
                if hit_item:
                    ed.selected = hit_item
                    ed.checkpoint()
                    ed.drag_base = (0.0, 0.0)
                else:
                    saved = ed.hit_saved_annot(px, py)
                    ed.selected = saved
                    ed.drag_base = None
            area.queue_draw()

        def on_drag_update(_g, dx, dy):
            pdx, pdy = dx / ed.zoom, dy / ed.zoom
            if ed.tool == "pen" and ed.live_stroke is not None:
                sx, sy = ed.live_stroke[0]
                ed.live_stroke.append((sx + pdx, sy + pdy))
            elif ed.tool in ("highlight", "redact", "shape", "crop") and ed.rubber:
                x0, y0, _, _ = ed.rubber
                ed.rubber = (x0, y0, x0 + pdx, y0 + pdy)
            elif (
                ed.tool == "select"
                and ed.selected in ed.pending
                and ed.drag_base is not None
            ):
                lx, ly = ed.drag_base
                ed.move_item(ed.selected, pdx - lx, pdy - ly)
                ed.drag_base = (pdx, pdy)
            area.queue_draw()

        finish_redact_drag = {"fn": lambda: None}

        def on_drag_end(_g, _dx, _dy):
            if ed.tool == "pen" and ed.live_stroke and len(ed.live_stroke) > 1:
                ed.checkpoint()
                ed.pending.append({"kind": "ink", "page": ed.page_no,
                                   "strokes": [ed.live_stroke],
                                   "color": list(ed.pen_color), "width": PEN_WIDTH})
            ed.live_stroke = None
            if ed.tool == "highlight" and ed.rubber:
                x0, y0, x1, y1 = ed.rubber
                if abs(x1 - x0) > 3 and abs(y1 - y0) > 3:
                    ed.checkpoint()
                    ed.pending.append({"kind": "highlight", "page": ed.page_no,
                                       "x0": x0, "y0": y0, "x1": x1, "y1": y1})
            if ed.tool == "shape" and ed.rubber:
                x0, y0, x1, y1 = ed.rubber
                if max(abs(x1 - x0), abs(y1 - y0)) > 3:
                    ed.checkpoint()
                    ed.pending.append({
                        "kind": "shape", "page": ed.page_no,
                        "shape": ed.shape_kind,
                        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                        "color": list(ed.pen_color), "width": PEN_WIDTH,
                    })
            if ed.tool == "crop" and ed.rubber:
                x0, y0, x1, y1 = ed.rubber
                if abs(x1 - x0) > 3 and abs(y1 - y0) > 3:
                    crop = [
                        min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1),
                    ]
                    ed.checkpoint()
                    transform_pending_for_crop(ed.pending, ed.page_no, crop)
                    ed.page_preview.add_crop_pages([ed.page_no + 1], crop)
                    ed.invalidate_view()
                    on_sidebar_change()
                    toast("Crop not applied until Save")
            if ed.tool == "redact" and ed.rubber:
                x0, y0, x1, y1 = ed.rubber
                if abs(x1 - x0) > 3 and abs(y1 - y0) > 3:
                    ed.checkpoint()
                    band = pymupdf.Rect(
                        min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
                    )
                    added: list[dict] = []
                    if ed.redact_free_rect:
                        added.append({
                            "kind": "redact", "page": ed.page_no,
                            "x0": band.x0, "y0": band.y0, "x1": band.x1, "y1": band.y1,
                        })
                    else:
                        for w in ed.page().get_text("words"):
                            wr = pymupdf.Rect(w[:4])
                            if wr.intersects(band):
                                added.append({
                                    "kind": "redact", "page": ed.page_no,
                                    "x0": wr.x0, "y0": wr.y0, "x1": wr.x1, "y1": wr.y1,
                                    "match": w[4],
                                })
                        if not added:
                            added.append({
                                "kind": "redact", "page": ed.page_no,
                                "x0": band.x0, "y0": band.y0, "x1": band.x1, "y1": band.y1,
                            })
                    ed.pending.extend(added)
                    finish_redact_drag["fn"]()
            ed.rubber = None
            ed.drag_base = None
            area.queue_draw()
            refresh_title()

        drag.connect("drag-begin", on_drag_begin)
        drag.connect("drag-update", on_drag_update)
        drag.connect("drag-end", on_drag_end)
        area.add_controller(drag)

        # -- toolbar ------------------------------------------------------

        css = Gtk.CssProvider()
        _light = not _color_scheme_is_dark()
        _bg, _fg = _theme_colors(win)
        chrome["desk"] = _desk_rgb(_bg, _light)
        chrome["fg"] = _fg
        chrome["light"] = _light
        chrome["shadows"] = SHADOWS_LIGHT if _light else SHADOWS_DARK
        css.load_from_data(_editorial_css(_light))
        if show_window_controls:
            css.load_from_data(WINDOW_CONTROLS_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        rail_css = Gtk.CssProvider()
        rail_css.load_from_data(_overlay_rail_css())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            rail_css,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )

        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        toolbar.add_css_class("omapdf-overlay-toolbar")
        toolbar.set_can_target(True)
        tools = {}
        first_btn = None

        def set_tool(name):
            ed.tool = name
            if not tools[name].get_active():
                tools[name].set_active(True)

        # -- vector icon set: one language, one stroke weight -------------

        def _path(ctx, pts):
            ctx.move_to(*pts[0])
            for p in pts[1:]:
                ctx.line_to(*p)

        def _ink(ctx, color, width):
            ctx.set_source_rgba(*color)
            ctx.set_line_width(width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)

        def icon_widget(painter):
            da = Gtk.DrawingArea()
            da.set_content_width(18)
            da.set_content_height(18)
            da.set_halign(Gtk.Align.CENTER)
            da.set_valign(Gtk.Align.CENTER)

            def dr(widget, ctx, _w, _h):
                c = widget.get_color()
                painter(ctx, (c.red, c.green, c.blue, c.alpha))

            da.set_draw_func(dr)
            return da

        def paint_pointer(ctx, fg):
            ctx.set_source_rgba(*fg)
            _path(ctx, [(5, 2), (5, 14), (8.2, 11.4), (10, 15.4),
                        (12.1, 14.4), (10.3, 10.6), (14.6, 10.3)])
            ctx.close_path()
            ctx.fill()

        def paint_sidebar(ctx, fg):
            _ink(ctx, fg, 1.5)
            ctx.rectangle(2.5, 3.5, 13, 11)
            ctx.stroke()
            ctx.set_source_rgba(*fg)
            ctx.rectangle(2.5, 3.5, 4.5, 11)
            ctx.fill()

        def paint_pen(ctx, _fg):
            ink = (*ed.pen_color, 1.0)
            _ink(ctx, ink, 2.6)
            _path(ctx, [(5.6, 12.4), (13.0, 5.0)])
            ctx.stroke()
            _ink(ctx, ink, 1.4)
            _path(ctx, [(3.6, 14.4), (5.6, 12.4)])
            ctx.stroke()
            ctx.set_source_rgba(*ink)
            ctx.arc(5.6, 12.4, 2.0, 0, 2 * math.pi)
            ctx.fill()

        def paint_highlighter(ctx, fg):
            _ink(ctx, fg, 1.5)
            _path(ctx, [(6.2, 9.3), (10.6, 3.6), (13.6, 6.0), (9.2, 11.7)])
            ctx.close_path()
            ctx.stroke()
            _path(ctx, [(6.2, 9.3), (5.0, 12.2), (9.2, 11.7)])
            ctx.close_path()
            ctx.set_source_rgba(*fg)
            ctx.fill()
            ctx.set_source_rgb(0.97, 0.85, 0.30)
            ctx.rectangle(3.0, 14.4, 12.0, 2.4)
            ctx.fill()

        def paint_text(ctx, fg):
            _ink(ctx, fg, 1.6)
            _path(ctx, [(4.5, 4.2), (13.5, 4.2)])
            ctx.stroke()
            _path(ctx, [(4.5, 4.2), (4.5, 5.2)])
            ctx.stroke()
            _path(ctx, [(13.5, 4.2), (13.5, 5.2)])
            ctx.stroke()
            _path(ctx, [(9, 4.2), (9, 14.6)])
            ctx.stroke()

        def paint_note(ctx, fg):
            _ink(ctx, fg, 1.5)
            r = 2.5
            x0, y0, x1, y1 = 2.5, 3.0, 15.5, 11.5
            ctx.new_sub_path()
            ctx.arc(x1 - r, y0 + r, r, -math.pi / 2, 0)
            ctx.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
            ctx.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi)
            ctx.arc(x0 + r, y0 + r, r, math.pi, 1.5 * math.pi)
            ctx.close_path()
            ctx.stroke()
            ctx.set_source_rgba(*fg)
            _path(ctx, [(6.2, 11.9), (5.4, 15.4), (9.6, 11.9)])
            ctx.close_path()
            ctx.fill()

        def paint_sign(ctx, fg):
            _ink(ctx, fg, 1.7)
            ctx.move_to(3.2, 12.0)
            ctx.curve_to(5.8, 3.6, 8.2, 4.4, 7.4, 8.8)
            ctx.curve_to(6.8, 12.2, 9.4, 12.0, 10.8, 9.2)
            ctx.stroke()
            _ink(ctx, fg, 1.3)
            _path(ctx, [(3.0, 15.2), (15.0, 15.2)])
            ctx.stroke()

        def paint_spark(ctx, fg):
            # Four-point spark: "ask the agent".
            ctx.set_source_rgba(*fg)
            _path(ctx, [(9, 2.2), (10.7, 7.3), (15.8, 9), (10.7, 10.7),
                        (9, 15.8), (7.3, 10.7), (2.2, 9), (7.3, 7.3)])
            ctx.close_path()
            ctx.fill()

        def paint_share(ctx, fg):
            # Arrow rising out of a tray — the universal "send it somewhere".
            _ink(ctx, fg, 1.6)
            _path(ctx, [(4.0, 9.5), (4.0, 14.5), (14.0, 14.5), (14.0, 9.5)])
            ctx.stroke()
            _path(ctx, [(9.0, 3.0), (9.0, 11.0)])
            ctx.stroke()
            _path(ctx, [(6.2, 5.6), (9.0, 2.8), (11.8, 5.6)])
            ctx.stroke()

        def paint_check(ctx, _fg):
            _ink(ctx, (*CHECK_COLOR, 1.0), 2.3)
            _path(ctx, [(3.8, 9.8), (7.4, 13.4), (14.2, 4.6)])
            ctx.stroke()

        def paint_cross(ctx, _fg):
            _ink(ctx, (*CROSS_COLOR, 1.0), 2.3)
            _path(ctx, [(4.8, 4.8), (13.2, 13.2)])
            ctx.stroke()
            _path(ctx, [(13.2, 4.8), (4.8, 13.2)])
            ctx.stroke()

        def paint_redact(ctx, fg):
            _ink(ctx, fg, 1.5)
            ctx.rectangle(3.5, 4.0, 11.0, 10.5)
            ctx.stroke()
            ctx.set_source_rgba(0, 0, 0, 0.75)
            ctx.rectangle(4.5, 5.0, 9.0, 8.5)
            ctx.fill()

        def paint_shapes(ctx, fg):
            _ink(ctx, fg, 1.5)
            ctx.rectangle(3.0, 4.0, 11.5, 9.5)
            ctx.stroke()
            ctx.move_to(4.5, 13.5)
            ctx.line_to(13.5, 4.5)
            ctx.stroke()

        def paint_crop(ctx, fg):
            _ink(ctx, fg, 1.6)
            ctx.rectangle(3.0, 3.5, 15.0, 12.5)
            ctx.stroke()
            for hx, hy in ((3, 3.5), (15, 3.5), (3, 12.5), (15, 12.5)):
                ctx.rectangle(hx - 1.2, hy - 1.2, 2.4, 2.4)
                ctx.stroke()

        def make_tool(name, tip, painter):
            nonlocal first_btn
            btn = Gtk.ToggleButton()
            btn.add_css_class("tool-slim")
            btn.add_css_class("tool-icon")
            btn.set_child(icon_widget(painter))
            btn.set_tooltip_text(tip)
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)
            btn.connect("toggled", lambda b: b.get_active() and setattr(ed, "tool", name))
            tools[name] = btn
            return btn

        def rail_sep():
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            toolbar.append(sep)

        side_toggle = Gtk.ToggleButton()
        side_toggle.add_css_class("tool-slim")
        side_toggle.add_css_class("tool-icon")
        side_toggle.set_child(icon_widget(paint_sidebar))
        side_toggle.set_tooltip_text("Thumbnails sidebar (F9)")

        make_tool("select", "Select — click an item, drag to move (Esc deselects, Del removes)",
                  paint_pointer)
        # Pen and its color share one button: the pen nib is drawn in the
        # current ink color; tapping the pen while it is ALREADY the active
        # tool opens the palette. One slot, no hover needed — touch-friendly.
        pen_btn = make_tool("pen", "Pen — freehand ink (tap again for colors)", paint_pen)
        pen_icon = pen_btn.get_child()

        def show_pen_color():
            pen_icon.queue_draw()

        color_pop = Gtk.Popover()
        color_pop.set_parent(pen_btn)
        color_box = Gtk.Box(spacing=2)
        for cname, rgb_t in PEN_COLORS:
            cb = Gtk.Button()
            clabel = Gtk.Label()
            hexc = "#%02x%02x%02x" % tuple(int(c * 255) for c in rgb_t)
            clabel.set_markup(f'<span foreground="{hexc}" size="x-large">●</span>')
            cb.set_child(clabel)
            cb.set_tooltip_text(cname)
            cb.add_css_class("flat")

            def pick(_b, chosen=rgb_t):
                ed.pen_color = chosen
                show_pen_color()
                color_pop.popdown()
                set_tool("pen")

            cb.connect("clicked", pick)
            color_box.append(cb)
        color_pop.set_child(color_box)
        show_pen_color()

        pen_state = {"just_activated": False}
        pen_btn.connect(
            "toggled",
            lambda b: b.get_active() and pen_state.__setitem__("just_activated", True),
        )

        def on_pen_clicked(_b):
            # First tap arms the pen (toggled fired); a tap on the already-
            # active pen opens the palette instead.
            if pen_state["just_activated"]:
                pen_state["just_activated"] = False
            elif ed.tool == "pen":
                color_pop.popup()

        pen_btn.connect("clicked", on_pen_clicked)

        make_tool("highlight", "Highlighter — drag across a region", paint_highlighter)
        make_tool("text", "Text — click to type onto the page", paint_text)
        make_tool("note", "Sticky note — click to leave a comment", paint_note)
        sign_btn = make_tool(
            "sign",
            "Sign — pick a saved signature and drag it onto the page",
            paint_sign,
        )
        sign_pop = Gtk.Popover()
        sign_pop.set_parent(sign_btn)
        sign_pop.set_position(Gtk.PositionType.LEFT)
        sign_pop.set_autohide(True)
        sign_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sign_box.set_margin_top(10)
        sign_box.set_margin_bottom(10)
        sign_box.set_margin_start(10)
        sign_box.set_margin_end(10)
        sign_pop.set_child(sign_box)

        def _sign_pop_alive() -> bool:
            return popover_is_alive(sign_pop)

        def _sign_pop_set_autohide(value: bool) -> None:
            if not _sign_pop_alive():
                return
            try:
                sign_pop.set_autohide(value)
            except Exception:
                return

        def _sign_pop_popdown() -> None:
            if not _sign_pop_alive():
                return
            try:
                sign_pop.popdown()
            except Exception:
                return

        def _sign_pop_popup() -> None:
            if not _sign_pop_alive():
                return
            try:
                sign_pop.popup()
            except Exception:
                return

        def _flush_deferred_render() -> None:
            if pinch_state["pending_commit"]:
                pinch_state["pending_commit"] = False
                if pinch_state["commit_id"]:
                    GLib.source_remove(pinch_state["commit_id"])
                pinch_state["commit_id"] = GLib.idle_add(commit_pinch_zoom)
                return
            if pinch_state["deferred_render"]:
                pinch_state["deferred_render"] = False
                anchor = pinch_state["deferred_anchor"]
                pinch_state["deferred_anchor"] = None
                GLib.idle_add(lambda: (render_page(v_anchor=anchor), False)[1])

        def _clear_box(box):
            child = box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                box.remove(child)
                child = nxt

        def _sig_thumb_size() -> tuple[int, int]:
            return (168, 72)

        def rebuild_sign_popover():
            _clear_box(sign_box)
            names = sig_store.list_names()
            if not names:
                empty = Gtk.Label(label="No signatures yet — record one")
                empty.add_css_class("dim-label")
                empty.set_wrap(True)
                empty.set_xalign(0)
                sign_box.append(empty)
            else:
                gallery = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                gallery.set_valign(Gtk.Align.START)
                tw, th = _sig_thumb_size()
                for name in names:
                    thumb = Gtk.DrawingArea()
                    thumb.set_content_width(tw)
                    thumb.set_content_height(th)
                    thumb.set_can_target(False)
                    surface = ed._ensure_sig(name)

                    def paint_thumb(_a, ctx, w, h, surf=surface, n=name):
                        ctx.set_source_rgb(1, 1, 1)
                        ctx.paint()
                        if n == ed.sig_name:
                            ctx.set_source_rgb(*SELECT_COLOR)
                            ctx.set_line_width(1.5)
                            ctx.rectangle(0.75, 0.75, w - 1.5, h - 1.5)
                            ctx.stroke()
                        if surf is None:
                            return
                        scale = min(
                            (w - 8) / max(surf.get_width(), 1),
                            (h - 8) / max(surf.get_height(), 1),
                        )
                        dw, dh = surf.get_width() * scale, surf.get_height() * scale
                        ctx.translate((w - dw) / 2, (h - dh) / 2)
                        ctx.scale(scale, scale)
                        ctx.set_source_surface(surf, 0, 0)
                        ctx.paint()

                    thumb.set_draw_func(paint_thumb)
                    label = Gtk.Label(label=name)
                    label.set_can_target(False)
                    label.set_wrap(True)
                    label.set_max_width_chars(16)
                    label.set_justify(Gtk.Justification.CENTER)
                    label.set_xalign(0.5)
                    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                    card.add_css_class("omapdf-sig-card")
                    card.set_tooltip_text(f"Drag {name} onto the page")
                    card.append(thumb)
                    card.append(label)

                    def on_pick(_g, _n, _x, _y, n=name):
                        if sig_drag["dragging"]:
                            return
                        ed.sig_name = n
                        set_tool("sign")
                        gallery_child = gallery.get_first_child()
                        while gallery_child is not None:
                            gallery_child.queue_draw()
                            gallery_child = gallery_child.get_next_sibling()

                    pick = Gtk.GestureClick()
                    pick.connect("released", on_pick)
                    card.add_controller(pick)

                    sig_move = Gtk.GestureDrag()

                    def on_sig_drag_begin(_g, _x, _y, n=name):
                        sig_drag["active"] = True
                        sig_drag["dragging"] = False
                        _sign_pop_set_autohide(False)
                        ed.sig_name = n
                        set_tool("sign")

                    def on_sig_drag_update(_g, dx, dy):
                        if math.hypot(dx, dy) > 8:
                            sig_drag["dragging"] = True

                    def on_sig_drag_end(_g, dx, dy, n=name):
                        dragging = sig_drag["dragging"] and math.hypot(dx, dy) > 8
                        sig_drag["active"] = False
                        sig_drag["dragging"] = False
                        _sign_pop_set_autohide(True)

                        def finish():
                            if dragging:
                                xy = _pointer_in_widget(area)
                                if xy is not None:
                                    ax, ay = xy
                                    aw = area.get_width() or 0
                                    ah = area.get_height() or 0
                                    if 0 <= ax <= aw and 0 <= ay <= ah:
                                        px, py = to_page_point(ax, ay)
                                        place_named_signature(n, px, py)
                                        sig_drag["just_dropped"] = True

                                        def clear_drop_flag():
                                            sig_drag["just_dropped"] = False
                                            return False

                                        GLib.timeout_add(80, clear_drop_flag)
                            _sign_pop_popdown()
                            _flush_deferred_render()
                            return False

                        GLib.idle_add(finish)

                    sig_move.connect("drag-begin", on_sig_drag_begin)
                    sig_move.connect("drag-update", on_sig_drag_update)
                    sig_move.connect("drag-end", on_sig_drag_end)
                    card.add_controller(sig_move)
                    gallery.append(card)
                gallery_scroll = Gtk.ScrolledWindow()
                gallery_scroll.set_policy(
                    Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER
                )
                gallery_scroll.set_propagate_natural_width(True)
                gallery_scroll.set_propagate_natural_height(True)
                gallery_scroll.set_max_content_width(520)
                gallery_scroll.set_child(gallery)
                sign_box.append(gallery_scroll)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            actions.add_css_class("omapdf-sig-actions")
            rec = Gtk.Button(label="Record new")
            rec.add_css_class("suggested-action")

            def on_record(_b):
                _sign_pop_popdown()
                record_signature(next_sig_name())

            rec.connect("clicked", on_record)
            actions.append(rec)
            if names:
                rer = Gtk.Button(label=f"Re-record '{ed.sig_name}'")

                def on_rerecord(_b, n=ed.sig_name):
                    _sign_pop_popdown()
                    record_signature(n)

                rer.connect("clicked", on_rerecord)
                actions.append(rer)
            sign_box.append(actions)
            hint = Gtk.Label(
                label="Drag a signature onto the page, or click the page to place it.",
                wrap=True,
                xalign=0,
            )
            hint.add_css_class("dim-label")
            sign_box.append(hint)

        sig_ui["rebuild"] = rebuild_sign_popover
        sign_state = {"just_activated": False}
        sign_btn.connect(
            "toggled",
            lambda b: b.get_active() and sign_state.__setitem__("just_activated", True),
        )

        def on_sign_clicked(_b):
            rebuild_sign_popover()
            if sign_state["just_activated"]:
                sign_state["just_activated"] = False
                _sign_pop_popup()
            elif ed.tool == "sign":
                _sign_pop_popup()

        sign_btn.connect("clicked", on_sign_clicked)
        make_tool("check", "Checkmark stamp — places a ✓ on the page", paint_check)
        make_tool("cross", "Cross-out stamp — places an ✕ on the page", paint_cross)
        shape_btn = make_tool(
            "shape",
            "Shapes — drag line, arrow, rect, or oval (tap again to pick)",
            paint_shapes,
        )
        shape_pop = Gtk.Popover()
        shape_pop.set_parent(shape_btn)
        shape_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        shape_box.set_margin_top(8)
        shape_box.set_margin_bottom(8)
        shape_box.set_margin_start(8)
        shape_box.set_margin_end(8)
        for label, kind in (
            ("Line", "line"),
            ("Arrow", "arrow"),
            ("Rectangle", "rect"),
            ("Oval", "oval"),
        ):
            sb = Gtk.Button(label=label)
            sb.add_css_class("flat")
            sb.set_halign(Gtk.Align.FILL)
            sb.get_child().set_halign(Gtk.Align.START)

            def pick_shape(_b, chosen=kind):
                ed.shape_kind = chosen
                shape_pop.popdown()
                set_tool("shape")

            sb.connect("clicked", pick_shape)
            shape_box.append(sb)
        shape_hint = Gtk.Label(
            label="Uses the current pen color. Ghosts apply on Save.",
            wrap=True,
            xalign=0,
        )
        shape_hint.add_css_class("dim-label")
        shape_box.append(shape_hint)
        shape_pop.set_child(shape_box)
        shape_state = {"just_activated": False}
        shape_btn.connect(
            "toggled",
            lambda b: b.get_active() and shape_state.__setitem__("just_activated", True),
        )

        def on_shape_clicked(_b):
            if shape_state["just_activated"]:
                shape_state["just_activated"] = False
            elif ed.tool == "shape":
                shape_pop.popup()

        shape_btn.connect("clicked", on_shape_clicked)
        make_tool(
            "crop",
            "Crop page — drag the region to keep (CropBox; applies on Save)",
            paint_crop,
        )
        redact_btn = make_tool(
            "redact",
            "Redact — drag over text (tap again for free-rectangle mode)",
            paint_redact,
        )
        redact_pop = Gtk.Popover()
        redact_pop.set_parent(redact_btn)
        redact_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        redact_box.set_margin_top(8)
        redact_box.set_margin_bottom(8)
        redact_box.set_margin_start(8)
        redact_box.set_margin_end(8)
        free_rect_sw = Gtk.Switch(active=False, halign=Gtk.Align.END)
        free_row = Gtk.Box(spacing=8)
        free_row.append(Gtk.Label(label="Free rectangle (images, handwriting)", xalign=0))
        free_row.append(free_rect_sw)
        redact_box.append(free_row)
        redact_hint = Gtk.Label(
            label="Ghosts are not applied until Save.",
            wrap=True,
            xalign=0,
        )
        redact_hint.add_css_class("dim-label")
        redact_box.append(redact_hint)
        redact_pop.set_child(redact_box)
        free_rect_sw.connect(
            "notify::active",
            lambda _sw, _pspec: setattr(ed, "redact_free_rect", free_rect_sw.get_active()),
        )
        redact_state = {"just_activated": False}
        redact_btn.connect(
            "toggled",
            lambda b: b.get_active() and redact_state.__setitem__("just_activated", True),
        )

        def on_redact_clicked(_b):
            if redact_state["just_activated"]:
                redact_state["just_activated"] = False
            elif ed.tool == "redact":
                redact_pop.popup()

        redact_btn.connect("clicked", on_redact_clicked)
        tools["select"].set_active(True)

        page_label = Gtk.Label()
        prev_b = Gtk.Button(label="‹")
        next_b = Gtk.Button(label="›")
        prev_b.add_css_class("flat")
        next_b.add_css_class("flat")
        for nav_b in (prev_b, next_b):
            nav_b.add_css_class("tool-slim")
            nav_b.add_css_class("tool-icon")
        prev_b.set_tooltip_text("Previous page (PgUp)")
        next_b.set_tooltip_text("Next page (PgDn)")

        def goto_page(n):
            n = max(0, min(ed.page_count() - 1, n))
            if n != ed.page_no:
                ed.page_no = n
                ed.selected = None
                render_page()
                # A fresh page starts at its top, wherever the old one was.
                adj = scroller.get_vadjustment()
                GLib.idle_add(lambda: (adj.set_value(0), False)[1])

        def go(delta):
            goto_page(ed.page_no + delta)

        prev_b.connect("clicked", lambda _b: go(-1))
        next_b.connect("clicked", lambda _b: go(1))

        # The page indicator is a button: click it (or Ctrl+G) to jump to a page.
        page_btn = Gtk.MenuButton()
        page_btn.add_css_class("flat")
        page_btn.add_css_class("tool-slim")
        page_label.add_css_class("page-indicator")
        page_btn.set_child(page_label)
        page_btn.set_tooltip_text("Go to page (Ctrl+G)")
        goto_pop = Gtk.Popover()
        goto_entry = Gtk.Entry()
        goto_entry.set_placeholder_text("Page #")
        goto_entry.set_width_chars(8)
        goto_pop.set_child(goto_entry)
        page_btn.set_popover(goto_pop)

        def on_goto(_e):
            try:
                n = int(goto_entry.get_text().strip())
            except ValueError:
                return
            goto_pop.popdown()
            goto_entry.set_text("")
            goto_page(n - 1)

        goto_entry.connect("activate", on_goto)

        nav_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        nav_btns.add_css_class("omapdf-rail-row")
        nav_btns.set_halign(Gtk.Align.CENTER)
        nav_btns.append(prev_b)
        nav_btns.append(next_b)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        nav.add_css_class("omapdf-rail-nav")
        nav.set_halign(Gtk.Align.CENTER)
        nav.append(page_btn)
        nav.append(nav_btns)

        def update_nav():
            # Single-page documents get no pager at all; otherwise the
            # impossible direction is greyed out rather than hidden, so the
            # control keeps a stable shape.
            nav.set_visible(ed.page_count() > 1)
            prev_b.set_sensitive(ed.page_no > 0)
            next_b.set_sensitive(ed.page_no < ed.page_count() - 1)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("omapdf-ghost")
        undo_b = Gtk.Button()
        undo_b.set_child(icon_widget(paint_undo_glyph))
        redo_b = Gtk.Button()
        redo_b.set_child(icon_widget(paint_redo_glyph))
        undo_b.set_tooltip_text("Undo — steps back through edits AND saves (Ctrl+Z)")
        redo_b.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        for icon_b in (undo_b, redo_b):
            icon_b.add_css_class("tool-slim")
            icon_b.add_css_class("tool-icon")

        def do_undo():
            mark_self_write()
            was_save = ed.undo()
            sidebar_api["refresh"]()
            if was_save:
                render_page()
                toast("Save reverted — the items are editable ghosts again")
            else:
                render_page()
                toast("Undone")
            area.queue_draw()
            refresh_title()

        def do_redo():
            mark_self_write()
            was_save = ed.redo()
            if was_save:
                render_page()
                toast("Save re-applied")
            else:
                sidebar_api["refresh"]()
                render_page()
            area.queue_draw()
            refresh_title()

        undo_b.connect("clicked", lambda _b: do_undo())
        redo_b.connect("clicked", lambda _b: do_redo())
        zoom_dot = Gtk.Label()
        zoom_dot.add_css_class("zoom-indicator")
        zoom_btn = Gtk.MenuButton()
        zoom_btn.add_css_class("tool-slim")
        zoom_btn.set_child(zoom_dot)
        zoom_btn.set_tooltip_text("Zoom (pinch, Ctrl+scroll; Ctrl+0 fits page)")
        zoom_pop = Gtk.Popover()
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        def set_zoom(pct):
            anchor = capture_v_anchor()
            ed.zoom_pct = pct
            zoom_pop.popdown()
            render_page(v_anchor=anchor)

        for zlabel, zval in [("Fit page", None), ("50%", 50.0), ("75%", 75.0),
                             ("100%", 100.0), ("125%", 125.0), ("150%", 150.0),
                             ("200%", 200.0)]:
            zb = Gtk.Button(label=zlabel)
            zb.add_css_class("flat")
            zb.connect("clicked", lambda _b, v=zval: set_zoom(v))
            zoom_box.append(zb)
        zoom_pop.set_child(zoom_box)
        zoom_btn.set_popover(zoom_pop)

        search_btn = Gtk.ToggleButton()
        search_btn.set_child(Gtk.Image.new_from_icon_name("system-search-symbolic"))
        search_btn.set_tooltip_text("Search (Ctrl+F)")
        search_btn.add_css_class("tool-slim")
        search_btn.add_css_class("tool-icon")

        # -- ask the agent (Omarchy's native default agent) ---------------

        ask_btn = Gtk.MenuButton()
        ask_btn.set_child(icon_widget(paint_spark))
        ask_btn.set_tooltip_text("Ask your agent about this document")
        ask_btn.add_css_class("tool-slim")
        ask_btn.add_css_class("tool-icon")
        ask_pop = Gtk.Popover()
        # Shift left of the spark button so the popover stays inside the
        # window instead of overhanging the neighboring tile.
        ask_pop.set_has_arrow(False)
        ask_pop.set_offset(-110, 4)
        ask_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ask_box.set_margin_top(8)
        ask_box.set_margin_bottom(8)
        ask_box.set_margin_start(8)
        ask_box.set_margin_end(8)
        ask_entry = Gtk.Entry()
        ask_entry.set_placeholder_text("Ask about this document…")
        ask_entry.set_width_chars(26)
        ask_entry.set_hexpand(True)
        ask_send = Gtk.Button(label="Ask")
        ask_send.add_css_class("suggested-action")
        ask_row = Gtk.Box(spacing=6)
        ask_row.append(ask_entry)
        ask_row.append(ask_send)
        ask_hint = Gtk.Label(label="Opens your default agent with this file attached")
        ask_hint.add_css_class("dim-label")
        ask_hint.set_halign(Gtk.Align.START)
        ask_box.append(ask_row)
        ask_box.append(ask_hint)
        ask_pop.set_child(ask_box)
        ask_btn.set_popover(ask_pop)

        def on_ask(_e):
            import subprocess as sp

            question = ask_entry.get_text().strip() or "Review this document for me."
            ask_pop.popdown()
            ask_entry.set_text("")
            prompt = (
                f"{question}\n\nThe document is the PDF at \"{ed.path}\" — "
                "use omepreview to read or mark it up. It is open in the omepreview "
                "editor, which auto-reloads when you save changes to it."
            )
            try:
                sp.Popen(["omarchy-agent-prompt", prompt], start_new_session=True)
                toast("Sent to your agent — a window is opening")
            except FileNotFoundError:
                toast("omarchy agent launcher not found on this system")

        ask_entry.connect("activate", on_ask)
        ask_send.connect("clicked", on_ask)

        # -- share menu ---------------------------------------------------

        import shutil as _shutil

        share_btn = Gtk.MenuButton()
        share_btn.set_child(icon_widget(paint_share))
        share_btn.set_tooltip_text("Share — send this PDF somewhere")
        share_btn.add_css_class("tool-slim")
        share_btn.add_css_class("tool-icon")
        share_pop = Gtk.Popover()
        share_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        flatten_check = Gtk.CheckButton(label="Flatten copy first")
        flatten_check.set_tooltip_text(
            "Bake annotations and form fields in, so every viewer shows them"
        )

        def share_target():
            if ed.pending or ed.page_preview.has_changes():
                toast("Unsaved changes — Save before sharing")
                return None
            if flatten_check.get_active():
                out = str(Path(ed.path).with_name(Path(ed.path).stem + "-final.pdf"))
                engine.flatten(ed.path, output=out)
                toast(f"Sharing flattened copy: {Path(out).name}")
                return out
            return ed.path

        def share_action(fn):
            def go(_b):
                share_pop.popdown()
                path = share_target()
                if path:
                    try:
                        fn(path)
                    except Exception as exc:
                        toast(f"Share failed: {exc}")
            return go

        def add_share(label, fn, tooltip=None):
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.set_halign(Gtk.Align.FILL)
            b.get_child().set_halign(Gtk.Align.START)
            if tooltip:
                b.set_tooltip_text(tooltip)
            b.connect("clicked", share_action(fn))
            share_box.append(b)

        def copy_file(path):
            import subprocess as sp

            uri = Path(path).resolve().as_uri() + "\n"
            sp.run(["wl-copy", "-t", "text/uri-list"], input=uri.encode(), check=True)
            toast(f"Copied {Path(path).name} — paste it into a chat, email, or folder")

        def zip_copy(path):
            import zipfile

            zpath = Path(path).with_suffix(".zip")
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(path, Path(path).name)
            copy_file(zpath)

        def spawn(cmd):
            import subprocess as sp

            sp.Popen(cmd, start_new_session=True)

        add_share("Email…", lambda p: spawn(["xdg-email", "--attach", p]),
                  "Open your mail client with the PDF attached")
        if _shutil.which("localsend"):
            add_share("LocalSend…", lambda p: spawn(["localsend", p]),
                      "Send to a nearby device")
        if _shutil.which("wl-copy"):
            add_share("Copy file", copy_file,
                      "Puts the file itself on the clipboard")
            add_share("Zip & copy", zip_copy,
                      "Zips the PDF and puts the .zip on the clipboard")
        add_share("Show in folder", lambda p: spawn(["xdg-open", str(Path(p).parent)]))
        share_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        share_box.append(flatten_check)
        share_pop.set_child(share_box)
        share_btn.set_popover(share_pop)

        def refresh_save_style():
            dirty = ed.pending or ed.page_preview.has_changes()
            if dirty:
                save_btn.remove_css_class("omapdf-ghost")
                save_btn.add_css_class("omapdf-ink")
            else:
                save_btn.remove_css_class("omapdf-ink")
                save_btn.add_css_class("omapdf-ghost")

        save_style_hook["fn"] = refresh_save_style

        for w in (side_toggle, search_btn, ask_btn):
            toolbar.append(w)
        rail_sep()
        for w in (
            tools["select"], pen_btn, tools["highlight"], tools["text"], tools["note"],
            tools["sign"], tools["check"], tools["cross"], shape_btn, tools["crop"],
            redact_btn,
        ):
            toolbar.append(w)
        rail_sep()
        undo_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        undo_row.add_css_class("omapdf-rail-row")
        undo_row.set_halign(Gtk.Align.CENTER)
        undo_row.append(undo_b)
        undo_row.append(redo_b)
        toolbar.append(zoom_btn)
        toolbar.append(undo_row)
        toolbar.append(nav)
        bottom_spacer = Gtk.Box()
        bottom_spacer.set_vexpand(True)
        toolbar.append(bottom_spacer)
        for w in (share_btn, save_btn):
            toolbar.append(w)

        toolbar.set_vexpand(True)
        toolbar_wrap = Gtk.Box()
        toolbar_wrap.set_halign(Gtk.Align.END)
        toolbar_wrap.set_valign(Gtk.Align.FILL)
        toolbar_wrap.set_can_target(True)
        toolbar_wrap.append(toolbar)

        def celebrate_save():
            label = save_btn.get_child()
            save_btn.set_sensitive(False)
            save_btn.remove_css_class("omapdf-ghost")
            save_btn.remove_css_class("omapdf-ink")
            label.set_text("Saved")

            def restore():
                save_btn.set_sensitive(True)
                label.set_text("Save")
                refresh_save_style()
                return False

            GLib.timeout_add(1200, restore)

        # Toast: bottom-centre ink strip; floats over the page without layout jump.
        toast_label = Gtk.Label()
        toast_label.add_css_class("toast-banner")
        toast_revealer = Gtk.Revealer()
        toast_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        toast_revealer.set_transition_duration(220)
        toast_revealer.set_halign(Gtk.Align.CENTER)
        toast_revealer.set_valign(Gtk.Align.END)
        toast_state = {"timeout": 0}
        # Suppresses the disk watcher while omepreview itself writes the file.
        write_guard = {"until": 0}

        def mark_self_write():
            write_guard["until"] = GLib.get_monotonic_time() + 2_000_000

        def toast(msg):
            if toast_state["timeout"]:
                GLib.source_remove(toast_state["timeout"])
                toast_state["timeout"] = 0
            if not msg:
                toast_revealer.set_reveal_child(False)
                return
            toast_label.set_text(msg)
            toast_revealer.set_reveal_child(True)

            def hide():
                toast_state["timeout"] = 0
                toast_revealer.set_reveal_child(False)
                return False

            toast_state["timeout"] = GLib.timeout_add(5000, hide)

        def show_redact_intro(on_done):
            if ed.redact_modal_shown:
                on_done()
                return
            ed.redact_modal_shown = True
            dialog = Gtk.Window(transient_for=win, modal=True, title="Redaction")
            dialog.set_default_size(440, -1)
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            vbox.set_margin_top(16)
            vbox.set_margin_bottom(16)
            vbox.set_margin_start(16)
            vbox.set_margin_end(16)
            vbox.append(Gtk.Label(
                label=(
                    "Redactions are translucent ghosts until Save.\n\n"
                    "Save writes a new file by default (*_redacted.pdf). "
                    "The original stays untouched."
                ),
                wrap=True,
                xalign=0,
            ))
            copy_sw = Gtk.Switch(active=True, halign=Gtk.Align.END)
            copy_row = Gtk.Box(spacing=8)
            copy_row.append(Gtk.Label(
                label="Save as *_redacted.pdf (recommended)", hexpand=True, xalign=0,
            ))
            copy_row.append(copy_sw)
            vbox.append(copy_row)
            confirm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            confirm_box.append(Gtk.Label(
                label="Type REDACT to overwrite the original:", xalign=0,
            ))
            confirm_entry = Gtk.Entry()
            confirm_box.append(confirm_entry)
            confirm_box.set_visible(False)
            vbox.append(confirm_box)
            btn_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            cancel_btn = Gtk.Button(label="Cancel")
            ok_btn = Gtk.Button(label="Continue")
            ok_btn.add_css_class("suggested-action")
            btn_row.append(cancel_btn)
            btn_row.append(ok_btn)
            vbox.append(btn_row)
            dialog.set_child(vbox)

            def validate(_obj=None):
                inplace = not copy_sw.get_active()
                confirm_box.set_visible(inplace)
                ok_btn.set_sensitive(
                    not inplace or confirm_entry.get_text().strip() == "REDACT"
                )

            copy_sw.connect("notify::active", validate)
            confirm_entry.connect("changed", validate)
            validate()

            def accept():
                ed.redact_save_as_copy = copy_sw.get_active()
                dialog.close()
                on_done()

            def cancel():
                if ed.undo_stack and ed.undo_stack[-1]["kind"] == "pending":
                    ed.undo()
                dialog.close()

            ok_btn.connect("clicked", lambda _b: accept())
            cancel_btn.connect("clicked", lambda _b: cancel())
            dialog.present()

        def after_redact_drag():
            def done():
                toast("Redaction not applied until Save")
            show_redact_intro(done)

        finish_redact_drag["fn"] = after_redact_drag

        def on_save(_b):
            markup_ops = ed.to_ops()
            page_ops = copy.deepcopy(ed.page_preview.page_ops)
            if not markup_ops and not page_ops:
                toast("Nothing to save")
                return
            redact_ops = [op for op in markup_ops if op["op"] == "redact"]
            other_markup = [op for op in markup_ops if op["op"] != "redact"]
            file_before = Path(ed.path).read_bytes()
            pending_before = copy.deepcopy(ed.pending)
            page_ops_before = copy.deepcopy(ed.page_preview.page_ops)
            ed.doc.close()
            ed.invalidate_view()
            ed.page_preview._drop_scratch()
            mark_self_write()
            work_path = ed.path
            redacted_copy = None
            if redact_ops and ed.redact_save_as_copy:
                redacted_copy = str(
                    Path(ed.path).with_name(Path(ed.path).stem + "_redacted.pdf")
                )
                shutil.copy2(ed.path, redacted_copy)
                work_path = redacted_copy
            try:
                for op in page_ops:
                    engine.apply(work_path, [op], output=work_path)
                if other_markup:
                    engine.apply(work_path, other_markup, output=work_path)
                if redact_ops:
                    engine.apply(work_path, redact_ops, output=work_path)
            except Exception as exc:  # surface engine errors in the UI
                toast(f"Save failed: {exc}")
                if redacted_copy and Path(redacted_copy).exists():
                    Path(redacted_copy).unlink()
                ed.doc = pymupdf.open(ed.path)
                ed.invalidate_view()
                ed.page_preview.rebuild()
                render_page()
                return
            ed.doc = pymupdf.open(ed.path)
            ed.page_preview.clear()
            ed.invalidate_view()
            ed.record_save(file_before, pending_before, page_ops_before)
            ed.pending.clear()
            ed.selected = None
            ed.page_no = min(ed.page_no, ed.page_count() - 1)
            render_page()
            saved = len(page_ops) + len(markup_ops)
            if redacted_copy:
                toast(
                    f"Saved {saved} change(s) to {Path(redacted_copy).name} "
                    "— original unchanged"
                )
            else:
                toast(f"Saved {saved} change(s) — Ctrl+Z reverts the save")
            celebrate_save()

        save_btn.connect("clicked", on_save)

        keys = Gtk.EventControllerKey()

        def on_key(_c, keyval, _code, state):
            # Runs in capture phase so arrows reach us before the scroll
            # view eats them — but typing in any entry must stay untouched.
            focus = win.get_focus()
            if focus is not None and isinstance(focus, (Gtk.Text, Gtk.Editable)):
                return False
            ctrl = state & Gdk.ModifierType.CONTROL_MASK
            shift = state & Gdk.ModifierType.SHIFT_MASK
            step = 10.0 if shift else 2.0
            if ctrl and keyval == Gdk.KEY_s:
                on_save(None)
            elif ctrl and keyval == Gdk.KEY_f:
                search_btn.set_active(True)
            elif ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
                current = ed.zoom_pct if ed.zoom_pct else ed.zoom / (96 / 72) * 100
                ed.zoom_pct = min(400.0, current + 25)
                render_page(v_anchor=capture_v_anchor())
            elif ctrl and keyval == Gdk.KEY_minus:
                current = ed.zoom_pct if ed.zoom_pct else ed.zoom / (96 / 72) * 100
                ed.zoom_pct = max(25.0, current - 25)
                render_page(v_anchor=capture_v_anchor())
            elif ctrl and keyval == Gdk.KEY_0:
                ed.zoom_pct = None
                render_page(v_anchor=capture_v_anchor())
            elif keyval == Gdk.KEY_F9:
                side_toggle.set_active(not side_toggle.get_active())
            elif side_toggle.get_active():
                if ctrl and keyval == Gdk.KEY_v:
                    sidebar_api["paste_pages"]()
                    return True
                if sidebar_api["has_page_selection"]():
                    if ctrl and keyval == Gdk.KEY_c:
                        sidebar_api["copy_selected_pages"]()
                        return True
                    if ctrl and keyval == Gdk.KEY_x:
                        sidebar_api["cut_selected_pages"]()
                        return True
            elif sidebar_api["sidebar_focus"]["active"] or side_toggle.get_active():
                if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
                    sidebar_api["delete_selected_pages"]()
                    area.queue_draw()
                    refresh_title()
                    return True
                if ctrl and keyval == Gdk.KEY_r and shift:
                    sidebar_api["rotate_selected"](-90)
                    area.queue_draw()
                    refresh_title()
                    return True
                if ctrl and keyval == Gdk.KEY_r:
                    sidebar_api["rotate_selected"](90)
                    area.queue_draw()
                    refresh_title()
                    return True
                if keyval == Gdk.KEY_b:
                    sidebar_api["insert_blank_after_current"]()
                    area.queue_draw()
                    refresh_title()
                    return True
            elif ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z) and shift:
                do_redo()
            elif ctrl and keyval == Gdk.KEY_z:
                do_undo()
            elif ctrl and keyval == Gdk.KEY_y:
                do_redo()
            elif keyval == Gdk.KEY_Escape:
                ed.selected = None
            elif keyval == Gdk.KEY_r and not ctrl:
                set_tool("redact")
            elif keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and ed.selected:
                ed.checkpoint()
                if ed.selected.get("kind") == "saved_annot":
                    if not ed._annot_marked_deleted(ed.selected["page"], ed.selected["index"]):
                        ed.pending.append({
                            "kind": "delete_annot",
                            "page": ed.selected["page"],
                            "index": ed.selected["index"],
                            "rect": ed.selected["rect"],
                            "annot_type": ed.selected["annot_type"],
                        })
                    ed.selected = None
                elif ed.selected in ed.pending:
                    ed.pending.remove(ed.selected)
                    ed.selected = None
            elif ctrl and keyval == Gdk.KEY_g:
                page_btn.popup()
            elif keyval == Gdk.KEY_Page_Up:
                go(-1)
            elif keyval == Gdk.KEY_Page_Down:
                go(1)
            elif keyval == Gdk.KEY_Home:
                goto_page(0)
            elif keyval == Gdk.KEY_End:
                goto_page(ed.page_count() - 1)
            elif (
                ed.selected
                and ed.selected.get("kind") not in ("saved_annot", "field_fill", "delete_annot")
                and ed.selected in ed.pending
                and keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down)
            ):
                dx = {Gdk.KEY_Left: -step, Gdk.KEY_Right: step}.get(keyval, 0.0)
                dy = {Gdk.KEY_Up: -step, Gdk.KEY_Down: step}.get(keyval, 0.0)
                ed.move_item(ed.selected, dx, dy)
            elif keyval == Gdk.KEY_Up:
                go(-1)
            elif keyval == Gdk.KEY_Down:
                go(1)
            else:
                return False
            area.queue_draw()
            refresh_title()
            return True

        keys.connect("key-pressed", on_key)
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        win.add_controller(keys)

        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("omapdf-page-canvas")
        scroller.set_child(area)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_hexpand_set(True)

        # -- thumbnails sidebar -------------------------------------------

        def on_sidebar_navigate(idx):
            if idx != ed.page_no:
                ed.page_no = idx
                ed.selected = None
                render_page()

        def on_sidebar_change():
            ed.invalidate_view()
            ed.page_no = min(ed.page_no, max(0, ed.page_count() - 1))
            sidebar_api["refresh"]()
            render_page()
            refresh_title()

        sidebar_api = gui_pages.build_page_sidebar(
            ed, on_sidebar_navigate, on_sidebar_change, toast
        )
        win.insert_action_group("page", sidebar_api["actions"])
        side_list = sidebar_api["widget"]
        side_scroll = Gtk.ScrolledWindow()
        side_scroll.add_css_class("omapdf-thumb-rail")
        side_scroll.set_child(side_list)
        side_scroll.set_size_request(132, -1)
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side_revealer = Gtk.Revealer()
        side_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        side_revealer.set_child(side_scroll)
        side_revealer.set_hexpand(False)
        side_revealer.set_vexpand(True)
        side_revealer.set_halign(Gtk.Align.START)
        side_toggle.connect("toggled", lambda b: side_revealer.set_reveal_child(b.get_active()))

        # -- search -------------------------------------------------------

        search_bar = Gtk.SearchBar()
        search_entry = Gtk.SearchEntry()
        search_entry.set_width_chars(32)
        search_bar.set_child(search_entry)
        search_bar.connect_entry(search_entry)

        def run_search(term):
            ed.search_term = term
            doc = ed.viewing_doc()
            ed.search_hits = [
                (n, rect)
                for n in range(doc.page_count)
                for rect in (doc[n].search_for(term) if term else [])
            ]
            ed.search_pos = -1
            if ed.search_hits:
                goto_hit(0)
            else:
                toast(f"No matches for {term!r}" if term else "")
                area.queue_draw()

        def goto_hit(i):
            ed.search_pos = i % len(ed.search_hits)
            pno, rect = ed.search_hits[ed.search_pos]
            if pno != ed.page_no:
                ed.page_no = pno
                ed.selected = None
                render_page()
            toast(f"Match {ed.search_pos + 1} of {len(ed.search_hits)}")

            def scroll_to():
                adj = scroller.get_vadjustment()
                _, page_y = ed.page_origin
                adj.set_value(max(0, page_y + rect.y0 * ed.zoom - scroller.get_height() / 3))
                return False

            GLib.idle_add(scroll_to)
            area.queue_draw()

        search_entry.connect("search-changed", lambda e: run_search(e.get_text().strip()))
        search_entry.connect("activate", lambda _e: ed.search_hits and goto_hit(ed.search_pos + 1))
        search_entry.connect(
            "next-match", lambda _e: ed.search_hits and goto_hit(ed.search_pos + 1)
        )
        search_entry.connect(
            "previous-match", lambda _e: ed.search_hits and goto_hit(ed.search_pos - 1)
        )

        def on_search_toggle(btn):
            search_bar.set_search_mode(btn.get_active())
            if btn.get_active():
                search_entry.grab_focus()
            else:
                run_search("")

        search_btn.connect("toggled", on_search_toggle)
        search_bar.connect(
            "notify::search-mode-enabled",
            lambda bar, _p: search_btn.set_active(bar.get_search_mode()),
        )

        # Ctrl+scroll zoom on the page.
        scroll_ctl = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )

        def on_scroll(ctl, _dx, dy):
            if ctl.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
                current = ed.zoom_pct if ed.zoom_pct else ed.zoom / (96 / 72) * 100
                ed.zoom_pct = max(25.0, min(400.0, current - dy * 10))
                render_page(v_anchor=capture_v_anchor())
                return True
            return False

        scroll_ctl.connect("scroll", on_scroll)
        scroller.add_controller(scroll_ctl)

        pinch = Gtk.GestureZoom.new()
        pinch.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def pinch_committed_pct() -> float:
            return current_zoom_pct(ed.zoom_pct, ed.zoom)

        def _pinch_focus(gesture):
            """Scroller-relative Y and drawing-area XY of the pinch (else viewport center)."""
            return compute_pinch_focus(gesture, scroller, area)

        def on_pinch_begin(gesture, _seq):
            if sig_drag["active"]:
                return
            if pinch_state["commit_id"]:
                GLib.source_remove(pinch_state["commit_id"])
                pinch_state["commit_id"] = 0
            try:
                viewport_y, focus_area = _pinch_focus(gesture)
            except Exception:
                vadj = scroller.get_vadjustment()
                hadj = scroller.get_hadjustment()
                vw = float(hadj.get_page_size() or scroller.get_width() or 1.0)
                vh = float(vadj.get_page_size() or scroller.get_height() or 1.0)
                cx, cy = vw / 2.0, vh / 2.0
                viewport_y, focus_area = cy, (
                    float(hadj.get_value()) + cx,
                    float(vadj.get_value()) + cy,
                )
            start = pinch_committed_pct()
            pinch_state["start_pct"] = start
            pinch_state["live_pct"] = start
            ed.pinch_live_scale = 1.0
            ed.pinch_focus_area = focus_area
            pinch_state["anchor"] = {
                "page_y": page_y_at_focus(
                    page_origin_y=ed.page_origin[1],
                    zoom=ed.zoom,
                    vscroll=float(scroller.get_vadjustment().get_value()),
                    viewport_y=float(viewport_y),
                ),
                "viewport_y": float(viewport_y),
            }

        def on_pinch(_gesture, scale):
            start = pinch_state["start_pct"]
            if start is None:
                return
            live = pinch_live_pct(start, scale)
            pinch_state["live_pct"] = live
            ed.pinch_live_scale = pinch_pixmap_scale(start, live)
            zoom_dot.set_text(f"{int(live)}%")
            area.queue_draw()

        def commit_pinch_zoom():
            pinch_state["commit_id"] = 0
            if sig_drag["active"]:
                pinch_state["pending_commit"] = True
                return False
            live = pinch_state["live_pct"]
            anchor = pinch_state["anchor"]
            pinch_state["start_pct"] = None
            pinch_state["live_pct"] = None
            pinch_state["anchor"] = None
            pinch_state["pending_commit"] = False
            if live is None:
                ed.pinch_live_scale = 1.0
                ed.pinch_focus_area = None
                return False
            ed.zoom_pct = live
            render_page(v_anchor=anchor)
            return False

        def on_pinch_end(_gesture, _seq):
            if pinch_state["start_pct"] is None and pinch_state["live_pct"] is None:
                return
            if pinch_state["commit_id"]:
                GLib.source_remove(pinch_state["commit_id"])
            pinch_state["commit_id"] = GLib.idle_add(commit_pinch_zoom)

        pinch.connect("begin", on_pinch_begin)
        pinch.connect("scale-changed", on_pinch)
        pinch.connect("end", on_pinch_end)
        pinch.connect("cancel", on_pinch_end)
        scroller.add_controller(pinch)

        # Keep fit-page honest when the viewport changes — sidebar sliding
        # in or out, window resizes. Debounced so the revealer animation
        # causes one re-render, not thirty.
        fit_state = {"pending": False}

        def on_viewport_change(_adj, _p):
            if pinch_state["start_pct"] is not None:
                return
            if ed.zoom_pct is not None or fit_state["pending"]:
                return
            fit_state["pending"] = True

            def rerender():
                fit_state["pending"] = False
                if ed.zoom_pct is None and abs(fit_page_zoom() - ed.zoom) > 0.004:
                    render_page()
                return False

            GLib.timeout_add(130, rerender)

        scroller.get_hadjustment().connect("notify::page-size", on_viewport_change)

        def on_scroller_width(_widget, _pspec):
            if scroller.get_width() < 50:
                return
            if ed.page_surface is None or ed.page_surface.get_width() < 8:
                GLib.idle_add(lambda: (render_page(), False)[1])
            elif ed.zoom_pct is None:
                on_viewport_change(scroller.get_hadjustment(), None)

        scroller.connect("notify::width", on_scroller_width)

        def on_scroller_height(_widget, _pspec):
            if scroller.get_height() < 50:
                return
            if ed.zoom_pct is None:
                on_viewport_change(scroller.get_vadjustment(), None)

        scroller.connect("notify::height", on_scroller_height)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.set_hexpand(True)
        content.set_vexpand(True)
        content.append(side_revealer)
        content.append(scroller)
        toast_revealer.set_child(toast_label)
        cheer_label = Gtk.Label()
        cheer_label.set_halign(Gtk.Align.END)
        cheer_label.set_valign(Gtk.Align.START)
        cheer_label.set_margin_end(56)
        cheer_label.set_margin_top(8)
        cheer_label.set_can_target(False)
        overlay = Gtk.Overlay()
        overlay.set_child(content)
        overlay.set_vexpand(True)
        overlay.set_hexpand(True)
        overlay.add_overlay(toast_revealer)
        overlay.add_overlay(cheer_label)
        overlay.add_overlay(toolbar_wrap)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_vexpand(True)
        box.append(search_bar)
        box.append(overlay)
        win.set_child(box)
        if show_window_controls:
            header = Gtk.HeaderBar()
            header.add_css_class("omapdf-window-controls")
            header.set_show_title_buttons(True)
            header.set_title_widget(Gtk.Box())  # empty — tools stay on the rail
            win.set_titlebar(header)

        # Watch the file: when an agent (or anything else) saves changes to
        # it, refresh the view — the GUI half of the ask-the-agent loop.
        monitor = Gio.File.new_for_path(ed.path).monitor_file(
            Gio.FileMonitorFlags.NONE, None
        )

        def on_disk_change(_m, _f, _o, event):
            if event != Gio.FileMonitorEvent.CHANGES_DONE_HINT:
                return
            if GLib.get_monotonic_time() < write_guard["until"]:
                return

            def reload():
                if not Path(ed.path).is_file():
                    return False
                try:
                    ed.doc.close()
                    ed.doc = pymupdf.open(ed.path)
                except Exception:
                    return False
                ed.invalidate_view()
                ed.page_no = min(ed.page_no, ed.page_count() - 1)
                ed.page_preview.clear()
                render_page()
                if ed.pending or ed.page_preview.has_changes():
                    toast("Changed on disk — view refreshed; your unsaved items are kept")
                else:
                    toast("Updated by another program — reloaded")
                return False

            GLib.timeout_add(200, reload)

        monitor.connect("changed", on_disk_change)
        win._omapdf_monitor = monitor  # keep the watcher alive

        sidebar_api["refresh"]()
        if ed.page_count() > 1:
            side_toggle.set_active(True)

        def initial_render():
            render_page()
            if ed.pending:
                toast(
                    f"{len(ed.pending)} proposed change(s) loaded — "
                    "drag to adjust, Save to apply"
                )
            return False

        win.present()
        GLib.idle_add(initial_render)

    app.connect("activate", on_activate)
    app.run(None)
    return 0


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m omepreview.gui <doc.pdf> [ops.json]", file=sys.stderr)
        return 2
    return run(args[0], args[1] if len(args) > 1 else None)


if __name__ == "__main__":
    sys.exit(main())
