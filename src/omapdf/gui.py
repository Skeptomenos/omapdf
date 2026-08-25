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
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
import cairo
import pymupdf
from gi.repository import Gdk, Gtk

from . import engine
from . import signature as sig_store

CHECK = [[(0.0, 7.0), (4.5, 12.0), (14.0, 0.0)]]
CROSS = [[(0.0, 0.0), (12.0, 12.0)], [(12.0, 0.0), (0.0, 12.0)]]
STAMP_SIZE = 16.0  # points
INK_COLOR = (0.75, 0.1, 0.1)
PEN_WIDTH = 2.0


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
        if ops_file:
            self._load_proposals(ops_file)

    # ---- model ----------------------------------------------------------

    def page(self) -> pymupdf.Page:
        return self.doc[self.page_no]

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.pending))
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.pending)
            self.pending = self.undo_stack.pop()
            self.selected = None

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.pending)
            self.pending = self.redo_stack.pop()
            self.selected = None

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
            elif kind == "ink":
                self.pending.append({
                    "kind": "ink", "page": page, "strokes": op["strokes"],
                    "color": op.get("color", list(INK_COLOR)),
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
        if it["kind"] in ("sig", "text"):
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
    app = Gtk.Application(application_id="org.omapdf.Editor")

    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app)
        win.set_default_size(980, 900)

        area = Gtk.DrawingArea()

        def refresh_title():
            dot = " •" if ed.pending else ""
            win.set_title(f"{Path(ed.path).name}{dot} — omapdf")

        def render_page():
            z = 900 / ed.page().rect.width
            ed.zoom = z
            pix = ed.page().get_pixmap(matrix=pymupdf.Matrix(z, z))
            ed.page_surface = cairo.ImageSurface.create_from_png(
                io.BytesIO(pix.tobytes("png"))
            )
            area.set_content_width(pix.width)
            area.set_content_height(pix.height)
            page_label.set_text(f"{ed.page_no + 1} / {ed.doc.page_count}")
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
                _stroke_path(ctx, [ed.live_stroke], INK_COLOR, PEN_WIDTH)
            if ed.rubber:
                x0, y0, x1, y1 = ed.rubber
                ctx.set_source_rgba(1, 0.85, 0.1, 0.35)
                ctx.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
                ctx.fill()

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
            elif it["kind"] == "highlight":
                x0, y0, x1, y1 = ed.item_rect(it)
                ctx.set_source_rgba(1, 0.85, 0.1, 0.35)
                ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
                ctx.fill()
            else:
                _stroke_path(ctx, it["strokes"], it["color"], it["width"])
            if it is ed.selected:
                x0, y0, x1, y1 = ed.item_rect(it)
                ctx.set_source_rgba(0.15, 0.45, 0.95, 0.9)
                ctx.set_line_width(1.2)
                ctx.set_dash([4, 3])
                ctx.rectangle(x0 - 3, y0 - 3, x1 - x0 + 6, y1 - y0 + 6)
                ctx.stroke()
                ctx.set_dash([])

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

        def prompt_text(px, py):
            pop = Gtk.Popover()
            pop.set_parent(area)
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(px * ed.zoom), int(py * ed.zoom), 1, 1
            pop.set_pointing_to(rect)
            entry = Gtk.Entry()
            entry.set_placeholder_text("Type, then Enter")
            entry.set_width_chars(28)
            pop.set_child(entry)

            def commit(_e):
                text = entry.get_text().strip()
                pop.popdown()
                if text:
                    ed.checkpoint()
                    item = {"kind": "text", "page": ed.page_no, "x": px, "y": py,
                            "text": text, "size": 12.0}
                    ed.pending.append(item)
                    ed.selected = item
                    area.queue_draw()
                    refresh_title()

            entry.connect("activate", commit)
            pop.popup()
            entry.grab_focus()

        # -- input --------------------------------------------------------

        def add_stamp(strokes_template, px, py):
            ed.checkpoint()
            scale = STAMP_SIZE / 14.0
            strokes = [[(px + sx * scale, py + sy * scale) for sx, sy in s]
                       for s in strokes_template]
            item = {"kind": "ink", "page": ed.page_no, "strokes": strokes,
                    "color": list(INK_COLOR), "width": 2.4}
            ed.pending.append(item)
            ed.selected = item
            set_tool("select")

        click = Gtk.GestureClick()

        def on_click(_g, _n, cx, cy):
            px, py = cx / ed.zoom, cy / ed.zoom
            if ed.tool == "text":
                prompt_text(px, py)
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
                add_stamp(CHECK, px, py)
            elif ed.tool == "cross":
                add_stamp(CROSS, px, py)
            else:
                ed.selected = ed.hit(px, py)
            area.queue_draw()
            refresh_title()

        click.connect("pressed", on_click)
        area.add_controller(click)

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
                                   "strokes": [ed.live_stroke], "color": list(INK_COLOR),
                                   "width": PEN_WIDTH})
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

        header = Gtk.HeaderBar()
        tools = {}
        first_btn = None

        def set_tool(name):
            ed.tool = name
            if not tools[name].get_active():
                tools[name].set_active(True)

        def make_tool(name, icon, tip):
            nonlocal first_btn
            btn = Gtk.ToggleButton()
            btn.set_child(Gtk.Label(label=icon))
            btn.set_tooltip_text(tip)
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)
            btn.connect("toggled", lambda b: b.get_active() and setattr(ed, "tool", name))
            tools[name] = btn
            header.pack_start(btn)
            return btn

        make_tool("select", "⬚", "Select / drag (Esc deselects, Del removes)")
        make_tool("pen", "✎", "Pen — freehand ink")
        make_tool("highlight", "▆", "Highlight — drag a region")
        make_tool("text", "T", "Text — click to type")
        make_tool("sign", "✍", "Sign — click to place your signature")
        make_tool("check", "✓", "Check stamp")
        make_tool("cross", "✕", "Cross stamp")
        tools["select"].set_active(True)

        page_label = Gtk.Label()
        prev_b = Gtk.Button(label="‹")
        next_b = Gtk.Button(label="›")

        def go(delta):
            n = ed.page_no + delta
            if 0 <= n < ed.doc.page_count:
                ed.page_no = n
                ed.selected = None
                render_page()

        prev_b.connect("clicked", lambda _b: go(-1))
        next_b.connect("clicked", lambda _b: go(1))
        nav = Gtk.Box(spacing=4)
        nav.append(prev_b)
        nav.append(page_label)
        nav.append(next_b)
        header.set_title_widget(nav)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        undo_b = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        redo_b = Gtk.Button.new_from_icon_name("edit-redo-symbolic")
        undo_b.connect("clicked", lambda _b: (ed.undo(), area.queue_draw(), refresh_title()))
        redo_b.connect("clicked", lambda _b: (ed.redo(), area.queue_draw(), refresh_title()))
        header.pack_end(save_btn)
        header.pack_end(redo_b)
        header.pack_end(undo_b)
        win.set_titlebar(header)

        toast_label = Gtk.Label()
        toast_label.add_css_class("dim-label")

        def toast(msg):
            toast_label.set_text(msg)

        def on_save(_b):
            if not ed.pending:
                toast("Nothing to save")
                return
            ops = ed.to_ops()
            ed.doc.close()
            try:
                engine.apply(ed.path, ops)
            except Exception as exc:  # surface engine errors in the UI
                toast(f"Save failed: {exc}")
                ed.doc = pymupdf.open(ed.path)
                render_page()
                return
            ed.pending.clear()
            ed.undo_stack.clear()
            ed.redo_stack.clear()
            ed.selected = None
            ed.doc = pymupdf.open(ed.path)
            render_page()
            toast(f"Saved {len(ops)} change(s)")

        save_btn.connect("clicked", on_save)

        keys = Gtk.EventControllerKey()

        def on_key(_c, keyval, _code, state):
            ctrl = state & Gdk.ModifierType.CONTROL_MASK
            shift = state & Gdk.ModifierType.SHIFT_MASK
            step = 10.0 if shift else 2.0
            if ctrl and keyval == Gdk.KEY_s:
                on_save(None)
            elif ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z) and shift:
                ed.redo()
            elif ctrl and keyval == Gdk.KEY_z:
                ed.undo()
            elif ctrl and keyval == Gdk.KEY_y:
                ed.redo()
            elif keyval == Gdk.KEY_Escape:
                ed.selected = None
            elif keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and ed.selected:
                ed.checkpoint()
                ed.pending.remove(ed.selected)
                ed.selected = None
            elif keyval == Gdk.KEY_Page_Up:
                go(-1)
            elif keyval == Gdk.KEY_Page_Down:
                go(1)
            elif ed.selected and keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
                dx = {Gdk.KEY_Left: -step, Gdk.KEY_Right: step}.get(keyval, 0.0)
                dy = {Gdk.KEY_Up: -step, Gdk.KEY_Down: step}.get(keyval, 0.0)
                ed.move_item(ed.selected, dx, dy)
            else:
                return False
            area.queue_draw()
            refresh_title()
            return True

        keys.connect("key-pressed", on_key)
        win.add_controller(keys)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(area)
        scroller.set_vexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(scroller)
        box.append(toast_label)
        win.set_child(box)

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
