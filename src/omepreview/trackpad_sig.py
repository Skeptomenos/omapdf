"""Preview-style trackpad signature capture helpers.

macOS Preview lets you sign on the trackpad surface without clicking — the ink
follows finger position. Linux trackpads rarely expose true hover; we try GTK
pressure/proximity axes first, then treat very light contact (pressure ≈ 0) as
the drawing signal. See docs/signature-trackpad.md.
"""

from __future__ import annotations

# Pressure at or below this counts as "hover / light touch" drawing on touchpads.
LIGHT_PRESSURE = 0.12
# Mouse click-drag uses a full press; ignore pressure gating when button is down.
FULL_PRESSURE = 0.45


def should_capture(
    *,
    source_name: str | None,
    pressure: float | None,
    button1: bool,
    proximity_in: bool,
) -> bool:
    """Return True when the next canvas point should extend the current stroke."""
    if proximity_in:
        return True
    if button1:
        return True
    src = (source_name or "").lower()
    if "touchpad" in src or src.endswith("touchpad"):
        if pressure is None:
            return False
        # Light touch without a click: pressure above idle, below a firm press.
        return 0 < pressure <= LIGHT_PRESSURE and not button1
    if pressure is not None and 0 < pressure < FULL_PRESSURE and not button1:
        return True
    return False


def stroke_mode_label(
    *,
    touchpad_detected: bool,
    pressure_axis: bool,
    proximity_axis: bool,
) -> str:
    if proximity_axis:
        return "Move your finger on the trackpad — ink follows without clicking"
    if touchpad_detected and pressure_axis:
        return "Draw with a light touch on the trackpad — no click needed"
    if touchpad_detected:
        return (
            "Light touch on the trackpad to draw "
            "(hover without contact is not available on this device)"
        )
    return "Sign above the line — drag to draw, Clear to retry, Save when happy"
