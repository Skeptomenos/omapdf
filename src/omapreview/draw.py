#!/usr/bin/env python3
"""Signature drawing window (GTK4).

Preview-style trackpad capture: ink follows finger position with light touch
or tablet proximity when the device exposes it. Mouse click-drag remains as
fallback. Save renders strokes to a transparent, tightly-cropped PNG.

Runs under system python when the venv lacks PyGObject; callers use draw.run().
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from . import signature as sig_store
from .trackpad_sig import LIGHT_PRESSURE, should_capture, stroke_mode_label

STROKE_WIDTH = 3.5
CANVAS_W, CANVAS_H = 760, 300
PAD = 8  # transparent margin around the cropped signature


def run(out_path: str | Path, *, trackpad: bool = True) -> bool:
    """Open the drawing window; True if a signature was saved to out_path."""
    try:
        import gi  # noqa: F401  (venv python usually lacks it)
        return _gtk_main(str(out_path), trackpad=trackpad) == 0
    except ImportError:
        proc = subprocess.run(
            [_system_python(), __file__, str(out_path), "1" if trackpad else "0"]
        )
        return proc.returncode == 0


def run_and_save(name: str = "default", *, trackpad: bool = True) -> bool:
    """Draw a signature and store it under `name` in the signature store."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "signature.png"
        if not run(out, trackpad=trackpad):
            return False
        sig_store.add(out, name)
        return True


def _system_python() -> str:
    for candidate in ("/usr/bin/python3", "/usr/bin/python"):
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("no system python found for the GTK drawing window")


def _gtk_main(out_path: str, *, trackpad: bool = True) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    try:
        gi.require_foreign("cairo")
    except (ImportError, ValueError) as exc:
        raise SystemExit(
            "omapreview sig draw needs PyGObject cairo integration — install python3-gi-cairo."
        ) from exc
    import cairo
    from gi.repository import Gdk, Gtk

    strokes: list[list[tuple[float, float]]] = []
    saved = False
    state = {
        "drawing": False,
        "touchpad": False,
        "pressure_axis": False,
        "proximity_axis": False,
    }

    def draw_func(_area, ctx, width, height):
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()
        ctx.set_source_rgb(0.85, 0.85, 0.85)
        ctx.set_line_width(1)
        ctx.move_to(30, height * 0.72)
        ctx.line_to(width - 30, height * 0.72)
        ctx.stroke()
        _paint_strokes(ctx, strokes, cairo)

    def redraw(area):
        area.queue_draw()

    def append_point(x: float, y: float, area):
        if not state["drawing"]:
            strokes.append([(x, y)])
            state["drawing"] = True
        elif strokes:
            last = strokes[-1][-1]
            if abs(last[0] - x) > 0.4 or abs(last[1] - y) > 0.4:
                strokes[-1].append((x, y))
        redraw(area)

    def end_stroke():
        state["drawing"] = False

    def event_pressure(event) -> float | None:
        if event is None:
            return None
        for axis in (Gdk.AxisUse.PRESSURE, Gdk.AxisUse.DISTANCE):
            ok, val = event.get_axis(axis)
            if ok:
                if axis == Gdk.AxisUse.PRESSURE:
                    state["pressure_axis"] = True
                    return float(val)
                if val < 1.0:
                    state["proximity_axis"] = True
        return None

    def event_source_name(event) -> str | None:
        if event is None:
            return None
        device = event.get_device()
        if device is None:
            return None
        try:
            src = device.get_source()
            return Gdk.InputSource.get_name(src.type_id) if src else None
        except AttributeError:
            return str(device.get_source())

    def button1_down(event) -> bool:
        if event is None:
            return False
        return bool(event.get_state() & Gdk.ModifierType.BUTTON1_MASK)

    app = Gtk.Application(application_id="org.omapreview.SignatureDraw")

    def on_activate(app):
        nonlocal area, hint
        win = Gtk.ApplicationWindow(application=app, title="Draw your signature")
        win.set_default_size(CANVAS_W + 40, CANVAS_H + 120)

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

        if trackpad:
            legacy = Gtk.EventControllerLegacy()
            legacy.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

            def on_legacy(_ctrl, event):
                if event.type not in (
                    Gdk.EventType.MOTION_NOTIFY,
                    Gdk.EventType.TOUCH_BEGIN,
                    Gdk.EventType.TOUCH_UPDATE,
                    Gdk.EventType.TOUCH_END,
                    Gdk.EventType.BUTTON_PRESS,
                    Gdk.EventType.BUTTON_RELEASE,
                ):
                    return False
                src = event_source_name(event)
                if src and "touchpad" in src.lower():
                    state["touchpad"] = True
                pressure = event_pressure(event)
                prox = bool(state["proximity_axis"])
                active = should_capture(
                    source_name=src,
                    pressure=pressure,
                    button1=button1_down(event),
                    proximity_in=prox,
                )
                if event.type in (Gdk.EventType.TOUCH_END, Gdk.EventType.BUTTON_RELEASE):
                    end_stroke()
                    hint.set_text(
                        stroke_mode_label(
                            touchpad_detected=state["touchpad"],
                            pressure_axis=state["pressure_axis"],
                            proximity_axis=state["proximity_axis"],
                        )
                    )
                    return False
                if active and event.type in (
                    Gdk.EventType.MOTION_NOTIFY,
                    Gdk.EventType.TOUCH_BEGIN,
                    Gdk.EventType.TOUCH_UPDATE,
                    Gdk.EventType.BUTTON_PRESS,
                ):
                    ok, x, y = event.get_coords()
                    if ok:
                        append_point(x, y, area)
                    return False
                if event.type == Gdk.EventType.MOTION_NOTIFY and not active:
                    end_stroke()
                return False

            legacy.connect("event", on_legacy)
            area.add_controller(legacy)

            stylus = Gtk.EventControllerStylus()

            def on_stylus_proximity(_c, x, y, proximity):
                state["proximity_axis"] = True
                if proximity:
                    append_point(x, y, area)
                else:
                    end_stroke()
                hint.set_text(
                    stroke_mode_label(
                        touchpad_detected=state["touchpad"],
                        pressure_axis=state["pressure_axis"],
                        proximity_axis=state["proximity_axis"],
                    )
                )

            def on_stylus_motion(_c, x, y):
                pressure = _c.get_axis(Gdk.AxisUse.PRESSURE)
                if pressure is not None:
                    state["pressure_axis"] = True
                if should_capture(
                    source_name="stylus",
                    pressure=pressure,
                    button1=pressure is not None and pressure >= LIGHT_PRESSURE,
                    proximity_in=True,
                ):
                    append_point(x, y, area)

            stylus.connect("proximity", on_stylus_proximity)
            stylus.connect("motion", on_stylus_motion)
            area.add_controller(stylus)

        drag = Gtk.GestureDrag()

        def on_begin(_g, x, y):
            strokes.append([(x, y)])
            state["drawing"] = True
            redraw(area)

        def on_update(gesture, dx, dy):
            ok, sx, sy = gesture.get_start_point()
            if ok and strokes:
                strokes[-1].append((sx + dx, sy + dy))
                redraw(area)

        def on_end(_g, _x, _y):
            end_stroke()

        drag.connect("drag-begin", on_begin)
        drag.connect("drag-update", on_update)
        drag.connect("drag-end", on_end)
        area.add_controller(drag)

        def on_clear(_b):
            strokes.clear()
            state["drawing"] = False
            redraw(area)

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

        hint = Gtk.Label(
            label=stroke_mode_label(
                touchpad_detected=False,
                pressure_axis=False,
                proximity_axis=False,
            )
        )
        hint.add_css_class("dim-label")
        hint.set_wrap(True)
        hint.set_max_width_chars(72)
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
    hint = None
    app.connect("activate", on_activate)
    app.run(None)
    return 0 if saved else 1


def _paint_strokes(ctx, strokes, cairo):
    ctx.set_source_rgb(0.05, 0.05, 0.2)
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
    ctx = cairo.Context(surface)
    ctx.translate(-min_x, -min_y)
    _paint_strokes(ctx, strokes, cairo)
    surface.write_to_png(out_path)


if __name__ == "__main__":
    trackpad = True
    if len(sys.argv) == 3:
        trackpad = sys.argv[2] != "0"
        out = sys.argv[1]
    elif len(sys.argv) == 2:
        out = sys.argv[1]
    else:
        print("usage: draw.py <output.png> [trackpad:0|1]", file=sys.stderr)
        sys.exit(2)
    sys.exit(_gtk_main(out, trackpad=trackpad))
