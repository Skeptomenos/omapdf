"""Trackpad signature capture policy tests."""

from omapreview.trackpad_sig import (
    LIGHT_PRESSURE,
    should_capture,
    stroke_mode_label,
)


def test_button_click_always_captures():
    assert should_capture(
        source_name="mouse",
        pressure=None,
        button1=True,
        proximity_in=False,
    )


def test_proximity_captures_without_click():
    assert should_capture(
        source_name="tablet",
        pressure=None,
        button1=False,
        proximity_in=True,
    )


def test_touchpad_light_touch_without_click():
    assert should_capture(
        source_name="touchpad",
        pressure=LIGHT_PRESSURE * 0.5,
        button1=False,
        proximity_in=False,
    )


def test_touchpad_no_pressure_axis_needs_contact():
    assert not should_capture(
        source_name="touchpad",
        pressure=None,
        button1=False,
        proximity_in=False,
    )


def test_firm_touchpad_press_without_button_ignored():
    assert not should_capture(
        source_name="touchpad",
        pressure=0.9,
        button1=False,
        proximity_in=False,
    )


def test_stroke_mode_labels():
    assert "without clicking" in stroke_mode_label(
        touchpad_detected=True,
        pressure_axis=False,
        proximity_axis=True,
    )
    assert "not available" in stroke_mode_label(
        touchpad_detected=True,
        pressure_axis=False,
        proximity_axis=False,
    )
