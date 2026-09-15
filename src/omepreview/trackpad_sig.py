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
from typing import NamedTuple

# Constant-width fallback when the pad has no pressure axis.
FALLBACK_RADIUS = 1.15
# Pressure axis: lightest contact is a hairline; a modest rest-and-glide
# already thickens. Apple/libinput pads often sit in a low slice of the
# ABS range — that slice is treated as full width (ease-out), so max
# radius does not need a firm click / force-touch.
HAIRLINE_RADIUS = 0.45
MAX_RADIUS = 3.7
PRESSURE_FULL_AT = 0.16  # fraction of (pmax-pmin) that maps to MAX_RADIUS
PRESSURE_GAMMA = 0.40  # ease-out: mid-low u already near thick
STROKE_WIDTH = FALLBACK_RADIUS * 2  # docs / older callers: fallback diameter
SVG_PAD = 8.0
# Finger lift + new contact on an absolute pad looks like a teleport.
JUMP_PX = 80.0
_CAP_STEPS = 8
_RADIUS_EMA = 0.55


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


class InkPoint(NamedTuple):
    """Pad-local sample. `radius` is half the local ink width."""

    x: float
    y: float
    radius: float


def as_ink_point(point) -> InkPoint:
    if isinstance(point, InkPoint):
        return point
    if len(point) >= 3:
        return InkPoint(float(point[0]), float(point[1]), float(point[2]))
    return InkPoint(float(point[0]), float(point[1]), FALLBACK_RADIUS)


def pressure_to_radius(
    raw: int | float | None,
    pressure_range: tuple[float, float] | None,
) -> float:
    """Map a device pressure sample to ink radius.

    No pressure axis → thin constant fallback. Raw at or below the axis
    minimum → hairline. A small slice of the remaining range (see
    ``PRESSURE_FULL_AT``) already maps to ``MAX_RADIUS``, with an ease-out
    curve so mid-low normalized pressure is already near a thick radius.
    """
    if pressure_range is None:
        return FALLBACK_RADIUS
    if raw is None:
        return HAIRLINE_RADIUS
    pmin, pmax = float(pressure_range[0]), float(pressure_range[1])
    span = pmax - pmin
    if span <= 0:
        return FALLBACK_RADIUS
    u = (float(raw) - pmin) / span
    if u <= 0.0:
        return HAIRLINE_RADIUS
    t = min(1.0, u / PRESSURE_FULL_AT)
    t = t**PRESSURE_GAMMA
    return HAIRLINE_RADIUS + (MAX_RADIUS - HAIRLINE_RADIUS) * t


def _unit(dx: float, dy: float) -> tuple[float, float]:
    h = math.hypot(dx, dy)
    if h < 1e-9:
        return 1.0, 0.0
    return dx / h, dy / h


def _tangent_at(points: list[InkPoint], i: int) -> tuple[float, float]:
    if i == 0:
        return _unit(points[1].x - points[0].x, points[1].y - points[0].y)
    if i == len(points) - 1:
        return _unit(
            points[i].x - points[i - 1].x, points[i].y - points[i - 1].y
        )
    return _unit(
        points[i + 1].x - points[i - 1].x, points[i + 1].y - points[i - 1].y
    )


def _cap(
    cx: float, cy: float, radius: float, tx: float, ty: float, *, start: bool
) -> list[tuple[float, float]]:
    heading = math.atan2(ty, tx)
    a0 = heading - math.pi / 2 if start else heading + math.pi / 2
    pts: list[tuple[float, float]] = []
    for i in range(1, _CAP_STEPS):
        a = a0 - math.pi * (i / _CAP_STEPS)
        pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return pts


def ribbon_outline(points: list[InkPoint]) -> list[tuple[float, float]]:
    """Filled-ribbon polygon for a variable-width stroke (round caps)."""
    ink = [as_ink_point(p) for p in points]
    if len(ink) < 2:
        return []
    if math.hypot(ink[-1].x - ink[0].x, ink[-1].y - ink[0].y) < 1e-6 and all(
        math.hypot(p.x - ink[0].x, p.y - ink[0].y) < 1e-6 for p in ink
    ):
        r = ink[0].radius
        return [
            (
                ink[0].x + r * math.cos(i * 2 * math.pi / 16),
                ink[0].y + r * math.sin(i * 2 * math.pi / 16),
            )
            for i in range(16)
        ]
    lefts: list[tuple[float, float]] = []
    rights: list[tuple[float, float]] = []
    for i, p in enumerate(ink):
        tx, ty = _tangent_at(ink, i)
        nx, ny = -ty, tx
        lefts.append((p.x + nx * p.radius, p.y + ny * p.radius))
        rights.append((p.x - nx * p.radius, p.y - ny * p.radius))
    tx0, ty0 = _tangent_at(ink, 0)
    txn, tyn = _tangent_at(ink, len(ink) - 1)
    start_cap = _cap(ink[0].x, ink[0].y, ink[0].radius, tx0, ty0, start=True)
    end_cap = _cap(ink[-1].x, ink[-1].y, ink[-1].radius, txn, tyn, start=False)
    return start_cap + lefts + end_cap + list(reversed(rights))


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
        self.strokes: list[list[InkPoint]] = []
        self.drawing = False
        self.mapper = PadMapper(self.pad_w, self.pad_h)
        self._radius_ema: float | None = None

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
        self._radius_ema = None

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
        self._radius_ema = None

    def apply_abs(
        self,
        kind: str,
        x: float | None = None,
        y: float | None = None,
        *,
        pressure: int | None = None,
        pressure_range: tuple[int, int] | None = None,
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
        radius = pressure_to_radius(pressure, pressure_range)
        if kind == "down":
            self.end_stroke()
            return self.add_point(px, py, button1=False, radius=radius)
        return self.add_point(px, py, button1=False, radius=radius)

    def add_point(
        self,
        x: float,
        y: float,
        *,
        button1: bool = False,
        radius: float | None = None,
    ) -> bool:
        """Append a pad-local point. Returns True if captured."""
        if not should_capture(
            armed=self.armed, button1=button1, click_mode=self.click_mode
        ):
            if self.drawing:
                self.end_stroke()
            return False
        raw_r = FALLBACK_RADIUS if radius is None else float(radius)
        if self._radius_ema is None:
            self._radius_ema = raw_r
        else:
            self._radius_ema = _RADIUS_EMA * raw_r + (1.0 - _RADIUS_EMA) * self._radius_ema
        point = InkPoint(float(x), float(y), self._radius_ema)
        if not self.drawing:
            self.strokes.append([point])
            self.drawing = True
            return True
        last = self.strokes[-1][-1]
        if abs(last.x - point.x) > 0.4 or abs(last.y - point.y) > 0.4:
            self.strokes[-1].append(point)
        elif abs(last.radius - point.radius) > 0.08:
            self.strokes[-1][-1] = point
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
        from .fs_privacy import chmod_private_file

        chmod_private_file(path)
        return path


def strokes_to_svg(strokes: list) -> str:
    """Export variable-width ink as filled ribbons (not a single stroke-width)."""
    outlines: list[list[tuple[float, float]]] = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        outline = ribbon_outline([as_ink_point(p) for p in stroke])
        if len(outline) >= 3:
            outlines.append(outline)
    points = [p for o in outlines for p in o]
    if not points:
        raise ValueError("no strokes to export")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x = min(xs) - SVG_PAD
    min_y = min(ys) - SVG_PAD
    width = max(max(xs) - min_x + SVG_PAD, 1.0)
    height = max(max(ys) - min_y + SVG_PAD, 1.0)
    parts: list[str] = []
    for outline in outlines:
        cmds = [f"M {_fmt(outline[0][0] - min_x)} {_fmt(outline[0][1] - min_y)}"]
        cmds.extend(
            f"L {_fmt(x - min_x)} {_fmt(y - min_y)}" for x, y in outline[1:]
        )
        cmds.append("Z")
        parts.append(" ".join(cmds))
    path_d = " ".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" '
        f'viewBox="0 0 {_fmt(width)} {_fmt(height)}">\n'
        f'  <path d="{path_d}" fill="#0d0d33"/>\n'
        f"</svg>\n"
    )


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value
