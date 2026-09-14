"""omapdf edit — the GTK4 editor.

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
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
import cairo
import pymupdf
from gi.repository import Gdk, Gio, GLib, Gtk

from . import engine
from . import gui_pages
from . import signature as sig_store
from .page_preview import PagePreviewState

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

CSS = b"""
headerbar button.save-btn {
  background: linear-gradient(180deg, #4a95ee, #2f74d0);
  color: white;
  font-weight: 600;
  border: none;
  border-radius: 9px;
  min-width: 58px;
  min-height: 28px;
  padding-left: 12px;
  padding-right: 12px;
  box-shadow: 0 1px 2px alpha(black, 0.35), inset 0 1px 0 alpha(white, 0.16);
}
headerbar button.save-btn:hover {
  background: linear-gradient(180deg, #5aa2f4, #3a80dc);
}
headerbar button.save-btn:active { background: #2f74d0; }
headerbar button.save-btn.save-success {
  background: linear-gradient(180deg, #43b768, #2e9e4f);
}
headerbar button.tool-slim,
headerbar menubutton.tool-slim > button {
  background: transparent;
  border: none;
  box-shadow: none;
  border-radius: 8px;
  padding-left: 8px;
  padding-right: 8px;
  min-width: 0;
  min-height: 28px;
}
headerbar button.tool-slim:hover,
headerbar menubutton.tool-slim > button:hover { background: alpha(currentColor, 0.10); }
headerbar button.tool-slim:active,
headerbar menubutton.tool-slim > button:active { background: alpha(currentColor, 0.16); }
headerbar button.tool-slim:checked { background: alpha(#3584e4, 0.32); }
headerbar button.tool-icon,
headerbar menubutton.tool-icon > button { padding: 5px; min-width: 28px; min-height: 28px; }
headerbar .page-indicator { opacity: 0.85; font-weight: 500; }
headerbar separator {
  background: alpha(currentColor, 0.22);
  margin-top: 12px;
  margin-bottom: 12px;
  margin-left: 1px;
  margin-right: 1px;
}
label.toast-banner {
  background: rgba(35, 35, 40, 0.88);
  color: white;
  border-radius: 9px;
  padding: 7px 16px;
  margin-top: 8px;
}
listbox row.omapdf-thumb-selected {
  background: alpha(#2f74d0, 0.22);
  border-radius: 6px;
}
listbox row.omapdf-thumb-inserted {
  border: 1px solid alpha(#2e9e4f, 0.55);
  border-radius: 6px;
}
"""


def _png_surface(path: str) -> cairo.ImageSurface:
    return cairo.ImageSurface.create_from_png(path)


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
        self.sig_surface: cairo.ImageSurface | None = None
        self.live_stroke: list[tuple[float, float]] | None = None
        self.rubber: tuple[float, float, float, float] | None = None
        self.drag_base: tuple[float, float] | None = None
        self.pen_color = PEN_COLORS[1][1]
        self.zoom_pct: float | None = None  # None = fit width
        self.search_term = ""
        self.search_hits: list[tuple[int, pymupdf.Rect]] = []
        self.search_pos = -1
        self.page_preview = PagePreviewState(self.path)
        self.window: Gtk.Window | None = None
        self._view_doc: pymupdf.Document | None = None
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

    def page(self) -> pymupdf.Page:
        return self.viewing_doc()[self.page_no]

    def page_count(self) -> int:
        return self.viewing_doc().page_count

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

    def sig_aspect(self) -> float:
        surface = self._ensure_sig()
        return surface.get_height() / surface.get_width() if surface else 0.4

    def _ensure_sig(self):
        if self.sig_surface is None:
            try:
                self.sig_surface = _png_surface(str(sig_store.get("default")))
            except FileNotFoundError:
                self.sig_surface = None
        return self.sig_surface

    def _load_proposals(self, ops_file: str):
        payload = json.loads(Path(ops_file).read_text())
        for op in payload:
            kind = op.get("op")
            page = op.get("page", 1) - 1
            if kind == "place_signature":
                w = float(op.get("width", 180))
                self.pending.append({
                    "kind": "sig", "page": page, "x": op["at"][0], "y": op["at"][1],
                    "w": w, "h": w * self.sig_aspect(), "date": bool(op.get("date")),
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
        return ops

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
            return (min(it["x0"], it["x1"]), min(it["y0"], it["y1"]),
                    max(it["x0"], it["x1"]), max(it["y0"], it["y1"]))
        xs = [p[0] for s in it["strokes"] for p in s]
        ys = [p[1] for s in it["strokes"] for p in s]
        return min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4

    def hit(self, x, y):
        for it in reversed([p for p in self.pending if p["page"] == self.page_no]):
            x0, y0, x1, y1 = self.item_rect(it)
            if x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4:
                return it
        return None

    def move_item(self, it, dx, dy):
        if it["kind"] in ("sig", "text", "note"):
            it["x"] += dx
            it["y"] += dy
        elif it["kind"] == "highlight":
            for k in ("x0", "x1"):
                it[k] += dx
            for k in ("y0", "y1"):
                it[k] += dy
        else:
            it["strokes"] = [[(px + dx, py + dy) for px, py in s] for s in it["strokes"]]


def run(pdf: str, ops_file: str | None = None) -> int:
    ed = Editor(pdf, ops_file)
    app = Gtk.Application(
        application_id="org.omapdf.Editor", flags=Gio.ApplicationFlags.NON_UNIQUE
    )

    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app)
        win.set_default_size(980, 900)
        ed.window = win

        area = Gtk.DrawingArea()
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

        def refresh_title():
            dirty = ed.pending or ed.page_preview.has_changes()
            dot = " •" if dirty else ""
            win.set_title(f"{Path(ed.path).name}{dot} — omapdf")

        def fit_width_zoom():
            # The real viewport width: hadjustment page-size accounts for the
            # sidebar and window size; fall back before first allocation.
            avail = scroller.get_hadjustment().get_page_size()
            if avail < 100:
                avail = scroller.get_width()
            if avail < 100:
                avail = 900
            return (avail - 4) / ed.page().rect.width

        def render_page():
            if ed.zoom_pct is None:
                z = fit_width_zoom()
            else:
                z = ed.zoom_pct / 100 * (96 / 72)
            ed.zoom = z
            zoom_dot.set_text("Fit" if ed.zoom_pct is None else f"{int(ed.zoom_pct)}%")
            pix = ed.page().get_pixmap(matrix=pymupdf.Matrix(z, z))
            ed.page_surface = cairo.ImageSurface.create_from_png(
                io.BytesIO(pix.tobytes("png"))
            )
            area.set_content_width(pix.width)
            area.set_content_height(pix.height)
            page_label.set_text(f"{ed.page_no + 1} / {ed.page_count()}")
            update_nav()
            sidebar_api["highlight_current"](ed.page_no)
            area.queue_draw()
            refresh_title()

        # -- drawing ------------------------------------------------------

        def draw(_a, ctx, _w, _h):
            if ed.page_surface:
                ctx.set_source_surface(ed.page_surface, 0, 0)
                ctx.paint()
            ctx.scale(ed.zoom, ed.zoom)
            for it in ed.pending:
                if it["page"] == ed.page_no:
                    draw_item(ctx, it)
            if ed.live_stroke and len(ed.live_stroke) > 1:
                _stroke_path(ctx, [ed.live_stroke], ed.pen_color, PEN_WIDTH)
            if ed.rubber:
                x0, y0, x1, y1 = ed.rubber
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

        def draw_item(ctx, it):
            if it["kind"] == "sig":
                surface = ed._ensure_sig()
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
            else:
                _stroke_path(ctx, it["strokes"], it["color"], it["width"])
            if it is ed.selected:
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
            rect.x, rect.y, rect.width, rect.height = int(px * ed.zoom), int(py * ed.zoom), 1, 1
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
            rect.x, rect.y, rect.width, rect.height = int(px * ed.zoom), int(py * ed.zoom), 1, 1
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

        click = Gtk.GestureClick()

        def on_click(_g, n_press, cx, cy):
            px, py = cx / ed.zoom, cy / ed.zoom
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
                if ed._ensure_sig() is None:
                    toast("No signature saved — run: omapdf sig draw")
                    return
                ed.checkpoint()
                w = 160.0
                item = {"kind": "sig", "page": ed.page_no, "x": px - w / 2,
                        "y": py - w * ed.sig_aspect() / 2, "w": w,
                        "h": w * ed.sig_aspect(), "date": False}
                ed.pending.append(item)
                ed.selected = item
                set_tool("select")
            elif ed.tool == "check":
                add_stamp(CHECK, CHECK_COLOR, px, py)
            elif ed.tool == "cross":
                add_stamp(CROSS, CROSS_COLOR, px, py)
            else:
                ed.selected = hit_item
                if ed.selected is None:
                    try:
                        show_saved_annot(px, py)
                    except Exception as exc:
                        toast(f"Couldn't open annotation: {exc}")
                elif n_press >= 2 and ed.selected["kind"] in ("note", "text"):
                    edit_pending(ed.selected)
            area.queue_draw()
            refresh_title()

        click.connect("pressed", on_click)
        area.add_controller(click)

        # Hovering a note/text (pending or saved) previews its content.
        area.set_has_tooltip(True)

        def on_tooltip(_w, tx, ty, _kb, tooltip):
            px, py = tx / ed.zoom, ty / ed.zoom
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

        def on_drag_begin(_g, sx, sy):
            px, py = sx / ed.zoom, sy / ed.zoom
            if ed.tool == "pen":
                ed.live_stroke = [(px, py)]
            elif ed.tool == "highlight":
                ed.rubber = (px, py, px, py)
            elif ed.tool == "select":
                ed.selected = ed.hit(px, py)
                if ed.selected:
                    ed.checkpoint()
                    ed.drag_base = (0.0, 0.0)
            area.queue_draw()

        def on_drag_update(_g, dx, dy):
            pdx, pdy = dx / ed.zoom, dy / ed.zoom
            if ed.tool == "pen" and ed.live_stroke is not None:
                sx, sy = ed.live_stroke[0]
                ed.live_stroke.append((sx + pdx, sy + pdy))
            elif ed.tool == "highlight" and ed.rubber:
                x0, y0, _, _ = ed.rubber
                ed.rubber = (x0, y0, x0 + pdx, y0 + pdy)
            elif ed.tool == "select" and ed.selected and ed.drag_base is not None:
                lx, ly = ed.drag_base
                ed.move_item(ed.selected, pdx - lx, pdy - ly)
                ed.drag_base = (pdx, pdy)
            area.queue_draw()

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
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        header = Gtk.HeaderBar()
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
            _ink(ctx, fg, 1.9)
            _path(ctx, [(4.5, 4.2), (13.5, 4.2)])
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

        def make_tool(name, tip, painter):
            nonlocal first_btn
            btn = Gtk.ToggleButton()
            btn.add_css_class("tool-slim")
            btn.add_css_class("tool-icon")
            btn.set_valign(Gtk.Align.CENTER)
            btn.set_child(icon_widget(painter))
            btn.set_tooltip_text(tip)
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)
            btn.connect("toggled", lambda b: b.get_active() and setattr(ed, "tool", name))
            tools[name] = btn
            header.pack_start(btn)
            return btn

        def tool_sep():
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            header.pack_start(sep)

        side_toggle = Gtk.ToggleButton()
        side_toggle.add_css_class("tool-slim")
        side_toggle.add_css_class("tool-icon")
        side_toggle.set_valign(Gtk.Align.CENTER)
        side_toggle.set_child(icon_widget(paint_sidebar))
        side_toggle.set_tooltip_text("Thumbnails sidebar (F9)")
        header.pack_start(side_toggle)
        tool_sep()

        make_tool("select", "Select — click an item, drag to move (Esc deselects, Del removes)",
                  paint_pointer)
        tool_sep()
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
        tool_sep()
        make_tool("sign", "Sign — click to place your signature", paint_sign)
        make_tool("check", "Checkmark stamp — places a ✓ on the page", paint_check)
        make_tool("cross", "Cross-out stamp — places an ✕ on the page", paint_cross)
        tools["select"].set_active(True)

        page_label = Gtk.Label()
        prev_b = Gtk.Button(label="‹")
        next_b = Gtk.Button(label="›")
        prev_b.add_css_class("flat")
        next_b.add_css_class("flat")
        for nav_b in (prev_b, next_b):
            nav_b.add_css_class("tool-slim")
            nav_b.add_css_class("tool-icon")
            nav_b.set_valign(Gtk.Align.CENTER)
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
        page_btn.set_valign(Gtk.Align.CENTER)
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

        nav = Gtk.Box(spacing=4)
        nav.append(prev_b)
        nav.append(page_btn)
        nav.append(next_b)
        header.set_title_widget(nav)

        def update_nav():
            # Single-page documents get no pager at all; otherwise the
            # impossible direction is greyed out rather than hidden, so the
            # control keeps a stable shape.
            nav.set_visible(ed.page_count() > 1)
            prev_b.set_sensitive(ed.page_no > 0)
            next_b.set_sensitive(ed.page_no < ed.page_count() - 1)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("save-btn")
        save_btn.set_valign(Gtk.Align.CENTER)
        undo_b = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        redo_b = Gtk.Button.new_from_icon_name("edit-redo-symbolic")
        undo_b.set_tooltip_text("Undo — steps back through edits AND saves (Ctrl+Z)")
        redo_b.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        for icon_b in (undo_b, redo_b):
            icon_b.add_css_class("tool-slim")
            icon_b.add_css_class("tool-icon")
            icon_b.set_valign(Gtk.Align.CENTER)

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
        zoom_btn = Gtk.MenuButton()
        zoom_btn.add_css_class("tool-slim")
        zoom_btn.set_valign(Gtk.Align.CENTER)
        zoom_btn.set_child(zoom_dot)
        zoom_btn.set_tooltip_text("Zoom (Ctrl+scroll, Ctrl+0 fits width)")
        zoom_pop = Gtk.Popover()
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        def set_zoom(pct):
            ed.zoom_pct = pct
            zoom_pop.popdown()
            render_page()

        for zlabel, zval in [("Fit width", None), ("50%", 50.0), ("75%", 75.0),
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
        search_btn.set_valign(Gtk.Align.CENTER)

        # -- ask the agent (Omarchy's native default agent) ---------------

        ask_btn = Gtk.MenuButton()
        ask_btn.set_child(icon_widget(paint_spark))
        ask_btn.set_tooltip_text("Ask your agent about this document")
        ask_btn.add_css_class("tool-slim")
        ask_btn.add_css_class("tool-icon")
        ask_btn.set_valign(Gtk.Align.CENTER)
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
                "use omapdf to read or mark it up. It is open in the omapdf "
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
        share_btn.set_valign(Gtk.Align.CENTER)
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

        header.pack_end(save_btn)
        header.pack_end(share_btn)
        header.pack_end(ask_btn)
        header.pack_end(redo_b)
        header.pack_end(undo_b)
        header.pack_end(zoom_btn)
        header.pack_end(search_btn)
        win.set_titlebar(header)

        def celebrate_save():
            # A little cheer: the Save button flips green with a same-size 👍
            # (no layout jiggle), while a bigger thumbs-up pops in an overlay
            # floating just beneath it — small → big → settle — then fades.
            label = save_btn.get_child()
            save_btn.add_css_class("save-success")
            save_btn.set_sensitive(False)
            label.set_text("👍")
            frames = [(0, "11000"), (90, "18000"), (200, "24000"),
                      (330, "16000"), (450, "19000")]
            for delay, size in frames:
                GLib.timeout_add(
                    delay,
                    lambda s=size: (cheer_label.set_markup(f'<span size="{s}">👍</span>'), False)[1],
                )

            def restore():
                save_btn.remove_css_class("save-success")
                save_btn.set_sensitive(True)
                label.set_text("Save")
                cheer_label.set_text("")
                return False

            GLib.timeout_add(1400, restore)

        # Toast: a banner that slides down from under the header, floats over
        # the page (no layout jump), and dismisses itself after 5 seconds.
        toast_label = Gtk.Label()
        toast_label.add_css_class("toast-banner")
        toast_revealer = Gtk.Revealer()
        toast_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        toast_revealer.set_transition_duration(220)
        toast_revealer.set_halign(Gtk.Align.CENTER)
        toast_revealer.set_valign(Gtk.Align.START)
        toast_state = {"timeout": 0}
        # Suppresses the disk watcher while omapdf itself writes the file.
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

        def on_save(_b):
            markup_ops = ed.to_ops()
            page_ops = copy.deepcopy(ed.page_preview.page_ops)
            if not markup_ops and not page_ops:
                toast("Nothing to save")
                return
            file_before = Path(ed.path).read_bytes()
            pending_before = copy.deepcopy(ed.pending)
            page_ops_before = copy.deepcopy(ed.page_preview.page_ops)
            ed.doc.close()
            ed.invalidate_view()
            ed.page_preview._drop_scratch()
            mark_self_write()
            try:
                for op in page_ops:
                    engine.apply(ed.path, [op], output=ed.path)
                if markup_ops:
                    engine.apply(ed.path, markup_ops, output=ed.path)
            except Exception as exc:  # surface engine errors in the UI
                toast(f"Save failed: {exc}")
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
                render_page()
            elif ctrl and keyval == Gdk.KEY_minus:
                current = ed.zoom_pct if ed.zoom_pct else ed.zoom / (96 / 72) * 100
                ed.zoom_pct = max(25.0, current - 25)
                render_page()
            elif ctrl and keyval == Gdk.KEY_0:
                ed.zoom_pct = None
                render_page()
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
            elif keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and ed.selected:
                ed.checkpoint()
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
            elif ed.selected and keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
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
        scroller.set_child(area)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

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
        side_scroll.set_child(side_list)
        side_scroll.set_size_request(150, -1)
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side_revealer = Gtk.Revealer()
        side_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        side_revealer.set_child(side_scroll)
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
                adj.set_value(max(0, rect.y0 * ed.zoom - scroller.get_height() / 3))
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
                render_page()
                return True
            return False

        scroll_ctl.connect("scroll", on_scroll)
        scroller.add_controller(scroll_ctl)

        # Keep fit-width honest when the viewport changes — sidebar sliding
        # in or out, window resizes. Debounced so the revealer animation
        # causes one re-render, not thirty.
        fit_state = {"pending": False}

        def on_viewport_change(_adj, _p):
            if ed.zoom_pct is not None or fit_state["pending"]:
                return
            fit_state["pending"] = True

            def rerender():
                fit_state["pending"] = False
                if ed.zoom_pct is None and abs(fit_width_zoom() - ed.zoom) > 0.004:
                    render_page()
                return False

            GLib.timeout_add(130, rerender)

        scroller.get_hadjustment().connect("notify::page-size", on_viewport_change)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.append(side_revealer)
        content.append(scroller)
        toast_revealer.set_child(toast_label)
        cheer_label = Gtk.Label()
        cheer_label.set_halign(Gtk.Align.END)
        cheer_label.set_valign(Gtk.Align.START)
        cheer_label.set_margin_end(24)
        cheer_label.set_margin_top(2)
        cheer_label.set_can_target(False)
        overlay = Gtk.Overlay()
        overlay.set_child(content)
        overlay.add_overlay(toast_revealer)
        overlay.add_overlay(cheer_label)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(search_bar)
        box.append(overlay)
        win.set_child(box)

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
        render_page()
        if ed.pending:
            toast(f"{len(ed.pending)} proposed change(s) loaded — drag to adjust, Save to apply")
        win.present()

    app.connect("activate", on_activate)
    app.run(None)
    return 0


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m omapdf.gui <doc.pdf> [ops.json]", file=sys.stderr)
        return 2
    return run(args[0], args[1] if len(args) > 1 else None)


if __name__ == "__main__":
    sys.exit(main())
