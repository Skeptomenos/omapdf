"""Preview-style trackpad signature capture.

macOS Preview: Space starts recording; a finger resting on the pad *and
moving* draws; a click / press-down is not required. Hover-in-air is not
the model. Space again clears and re-records. Enter saves SVG.

Linux laptop pads already move the pointer without BUTTON1. While armed,
ink comes from the touchpad's absolute axes (evdev) when they can be
opened; relative pointer deltas are fallback only. `--click` is mouse
click-and-drag fallback only.
"""

from __future__ import annotations

import math
from pathlib import Path

STROKE_WIDTH = 3.5
SVG_PAD = 8.0
# Finger lift + new contact on an absolute pad looks like a teleport.
JUMP_PX = 80.0


def should_capture(
    *,
    armed: bool,
    button1: bool = False,
    click_mode: bool = False,
) -> bool:
    """True when this pointer sample should extend the stroke.

    Armed trackpad: motion without BUTTON1 must draw. Unarmed: no ink.
    Click mode: BUTTON1 is required (mouse fallback).
    """
    if not armed:
        return False
    if click_mode:
        return bool(button1)
    return True


def stroke_mode_label(
    *,
    armed: bool,
    click_mode: bool = False,
    has_ink: bool = False,
    abs_mode: bool = False,
    abs_denied: bool = False,
) -> str:
    if click_mode:
        if not armed:
            return "Space to start · click and drag to draw · Enter to save"
        if has_ink:
            return "Enter to save · Space clears and re-records"
        return "Click and drag on the pad · Enter saves · Space restarts"
    if abs_denied and not abs_mode:
        if not armed:
            return (
                "Space to record · relative pointer fallback — add your user "
                "to the input group for absolute pad mapping · Enter to save"
            )
        if has_ink:
            return "Enter to save · Space clears and starts over"
        return (
            "Relative pointer fallback (need /dev/input) — ink follows "
            "without clicking · Enter saves"
        )
    if not armed:
        return (
            "Space to record · rest a finger on the trackpad and move "
            "(no click) · lift ends a stroke · Enter to save"
        )
    if has_ink:
        return "Enter to save · Space clears and starts over"
    if abs_mode:
        return (
            "Finger on the pad draws at that spot — ink follows without "
            "clicking · lift ends a stroke · Enter saves"
        )
    return (
        "Move on the trackpad — ink follows without clicking · lift ends "
        "a stroke · Enter saves"
    )


class PadMapper:
    """Map grabbed pointer motion onto the on-screen pad.

    Relative mode (default, grab failed or pointer left the glass): finger
    deltas draw on the pad so the desktop cursor wandering is irrelevant.
    Absolute mode (pointer confined to the pad): the on-screen location is
    the pen.
    """

    def __init__(self, width: float, height: float):
        self.width = float(width)
        self.height = float(height)
        self.absolute = False
        self.last: tuple[float, float] | None = None
        self.pen = (self.width * 0.22, self.height * 0.58)

    def reset(self) -> None:
        self.last = None
        self.pen = (self.width * 0.22, self.height * 0.58)

    def feed(
        self, x: float, y: float, *, on_glass: bool = False
    ) -> tuple[float, float] | None:
        if self.absolute and on_glass:
            self.pen = (
                _clamp(x, 0.0, self.width),
                _clamp(y, 0.0, self.height),
            )
            self.last = (x, y)
            return self.pen
        if self.last is None:
            self.last = (x, y)
            return None
        dx = x - self.last[0]
        dy = y - self.last[1]
        self.last = (x, y)
        if math.hypot(dx, dy) > JUMP_PX:
            return None
        self.pen = (
            _clamp(self.pen[0] + dx, 0.0, self.width),
            _clamp(self.pen[1] + dy, 0.0, self.height),
        )
        return self.pen


class RecorderSession:
    """Keyboard + motion state machine. GTK drives this; tests do too."""

    def __init__(self, *, click_mode: bool = False, pad_size: tuple[float, float] = (520.0, 340.0)):
        self.click_mode = click_mode
        self.pad_w, self.pad_h = float(pad_size[0]), float(pad_size[1])
        self.armed = False
        self.grab_pointer = False
        self.abs_active = False
        self.strokes: list[list[tuple[float, float]]] = []
        self.drawing = False
        self.mapper = PadMapper(self.pad_w, self.pad_h)

    def has_ink(self) -> bool:
        return any(len(s) >= 2 for s in self.strokes)

    def handle_space(self) -> None:
        """Arm recording. If already armed or inked, clear and start over."""
        self.strokes.clear()
        self.drawing = False
        self.mapper.reset()
        self.armed = True
        self.grab_pointer = True
        self.abs_active = False

    def handle_enter(self) -> bool:
        """True when the session has ink to save. Disarms after a successful save."""
        if not self.has_ink():
            return False
        self.armed = False
        self.grab_pointer = False
        self.drawing = False
        return True

    def end_stroke(self) -> None:
        self.drawing = False
        self.mapper.last = None

    def apply_abs(
        self,
        kind: str,
        x: float | None = None,
        y: float | None = None,
    ) -> bool:
        """Contact from an absolute pad. `kind` is down / move / up.

        Finger up ends the stroke (no connecting line). Finger down at a
        new abs location starts a disconnected stroke at that mapped point.
        """
        if not self.armed or self.click_mode:
            return False
        if kind == "up":
            self.end_stroke()
            return True
        if x is None or y is None:
            return False
        px = _clamp(float(x), 0.0, self.pad_w)
        py = _clamp(float(y), 0.0, self.pad_h)
        if kind == "down":
            self.end_stroke()
            return self.add_point(px, py, button1=False)
        return self.add_point(px, py, button1=False)

    def add_point(self, x: float, y: float, *, button1: bool = False) -> bool:
        """Append a pad-local point. Returns True if captured."""
        if not should_capture(
            armed=self.armed, button1=button1, click_mode=self.click_mode
        ):
            if self.drawing:
                self.end_stroke()
            return False
        point = (float(x), float(y))
        if not self.drawing:
            self.strokes.append([point])
            self.drawing = True
            return True
        last = self.strokes[-1][-1]
        if abs(last[0] - point[0]) > 0.4 or abs(last[1] - point[1]) > 0.4:
            self.strokes[-1].append(point)
        return True

    def motion(
        self,
        x: float,
        y: float,
        *,
        button1: bool = False,
        on_glass: bool = False,
    ) -> bool:
        """Pointer sample in grab/window space; mapped onto the pad."""
        if not should_capture(
            armed=self.armed, button1=button1, click_mode=self.click_mode
        ):
            if self.drawing:
                self.end_stroke()
            return False
        mapped = self.mapper.feed(x, y, on_glass=on_glass)
        if mapped is None:
            if self.drawing and not (self.mapper.absolute and on_glass):
                self.end_stroke()
            return False
        return self.add_point(mapped[0], mapped[1], button1=button1)

    def write_svg(self, path: str | Path) -> Path:
        if not self.has_ink():
            raise ValueError("draw a signature first — Space to record, Enter to save")
        path = Path(path)
        path.write_text(strokes_to_svg(self.strokes), encoding="utf-8")
        return path


def strokes_to_svg(strokes: list[list[tuple[float, float]]]) -> str:
    points = [p for s in strokes for p in s]
    if not points:
        raise ValueError("no strokes to export")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x = min(xs) - SVG_PAD
    min_y = min(ys) - SVG_PAD
    width = max(max(xs) - min_x + SVG_PAD, 1.0)
    height = max(max(ys) - min_y + SVG_PAD, 1.0)
    parts: list[str] = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        cmds = [f"M {_fmt(stroke[0][0] - min_x)} {_fmt(stroke[0][1] - min_y)}"]
        cmds.extend(
            f"L {_fmt(x - min_x)} {_fmt(y - min_y)}" for x, y in stroke[1:]
        )
        parts.append(" ".join(cmds))
    path_d = " ".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" '
        f'viewBox="0 0 {_fmt(width)} {_fmt(height)}">\n'
        f'  <path d="{path_d}" fill="none" stroke="#0d0d33" '
        f'stroke-width="{STROKE_WIDTH}" stroke-linecap="round" '
        f'stroke-linejoin="round"/>\n'
        f"</svg>\n"
    )


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value
