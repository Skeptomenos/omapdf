#!/usr/bin/env python3
"""Signature drawing window (GTK4).

Draw with mouse, touchpad, or stylus; Save renders the strokes to a
transparent, tightly-cropped PNG at the path given on the command line.

This module runs standalone under the *system* python (which has PyGObject)
because omapdf's venv doesn't: `python3 draw.py /path/out.png`. run() handles
that hand-off, so callers just use omapdf.draw.run(out_path).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STROKE_WIDTH = 3.5
CANVAS_W, CANVAS_H = 760, 300
PAD = 8  # transparent margin around the cropped signature


def run(out_path: str | Path) -> bool:
    """Open the drawing window; True if a signature was saved to out_path."""
    try:
        import gi  # noqa: F401  (venv python usually lacks it)
        return _gtk_main(str(out_path)) == 0
    except ImportError:
        proc = subprocess.run([_system_python(), __file__, str(out_path)])
        return proc.returncode == 0


def _system_python() -> str:
    for candidate in ("/usr/bin/python3", "/usr/bin/python"):
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("no system python found for the GTK drawing window")


def _gtk_main(out_path: str) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    try:
        gi.require_foreign("cairo")
    except (ImportError, ValueError) as exc:
        raise SystemExit(
            "omapdf sig draw needs PyGObject cairo integration — install python3-gi-cairo."
        ) from exc
    import cairo
    from gi.repository import Gtk

    strokes: list[list[tuple[float, float]]] = []
    saved = False

    def draw_func(_area, ctx, width, height):
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()
        # Baseline guide, like the signature line on a form.
        ctx.set_source_rgb(0.85, 0.85, 0.85)
        ctx.set_line_width(1)
        ctx.move_to(30, height * 0.72)
        ctx.line_to(width - 30, height * 0.72)
        ctx.stroke()
        _paint_strokes(ctx, strokes, cairo)

    def redraw():
        area.queue_draw()

    app = Gtk.Application(application_id="org.omapdf.SignatureDraw")

    def on_activate(app):
        nonlocal area
        win = Gtk.ApplicationWindow(application=app, title="Draw your signature")
        win.set_default_size(CANVAS_W + 40, CANVAS_H + 100)

        header = Gtk.HeaderBar()
        clear_btn = Gtk.Button(label="Clear")
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        header.pack_start(clear_btn)
        header.pack_end(save_btn)
        win.set_titlebar(header)

        area = Gtk.DrawingArea()
        area.set_content_width(CANVAS_W)
        area.set_content_height(CANVAS_H)
        area.set_draw_func(draw_func)

        drag = Gtk.GestureDrag()

        def on_begin(_g, x, y):
            strokes.append([(x, y)])
            redraw()

        def on_update(gesture, dx, dy):
            ok, sx, sy = gesture.get_start_point()
            if ok and strokes:
                strokes[-1].append((sx + dx, sy + dy))
                redraw()

        drag.connect("drag-begin", on_begin)
        drag.connect("drag-update", on_update)
        area.add_controller(drag)

        def on_clear(_b):
            strokes.clear()
            redraw()

        def on_save(_b):
            nonlocal saved
            if not any(len(s) > 1 for s in strokes):
                win.set_title("Draw something first…")
                return
            _export_png(strokes, out_path, cairo)
            saved = True
            win.close()

        clear_btn.connect("clicked", on_clear)
        save_btn.connect("clicked", on_save)

        hint = Gtk.Label(label="Sign above the line — Clear to retry, Save when happy")
        hint.add_css_class("dim-label")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.append(area)
        box.append(hint)
        win.set_child(box)
        win.present()

    area = None
    app.connect("activate", on_activate)
    app.run(None)
    return 0 if saved else 1


def _paint_strokes(ctx, strokes, cairo):
    ctx.set_source_rgb(0.05, 0.05, 0.2)  # near-black ink with a hint of blue
    ctx.set_line_width(STROKE_WIDTH)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        ctx.move_to(*stroke[0])
        for point in stroke[1:]:
            ctx.line_to(*point)
        ctx.stroke()


def _export_png(strokes, out_path, cairo):
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    min_x, min_y = min(xs) - PAD, min(ys) - PAD
    width = int(max(xs) - min_x + PAD * 2)
    height = int(max(ys) - min_y + PAD * 2)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)  # transparent background
    ctx.translate(-min_x, -min_y)
    _paint_strokes(ctx, strokes, cairo)
    surface.write_to_png(out_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: draw.py <output.png>", file=sys.stderr)
        sys.exit(2)
    sys.exit(_gtk_main(sys.argv[1]))
