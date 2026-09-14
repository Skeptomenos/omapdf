"""Trackpad signature capture policy tests."""

from omepreview.trackpad_sig import (
    FALLBACK_RADIUS,
    HAIRLINE_RADIUS,
    MAX_RADIUS,
    InkPoint,
    PadMapper,
    RecorderSession,
    pressure_to_radius,
    ribbon_outline,
    should_capture,
    stroke_mode_label,
    strokes_to_svg,
)


def test_armed_motion_without_button_captures():
    assert should_capture(armed=True, button1=False, click_mode=False)
    session = RecorderSession()
    session.handle_space()
    assert session.add_point(10, 10, button1=False)
    assert session.add_point(24, 18, button1=False)
    assert session.has_ink()


def test_unarmed_motion_does_not_ink():
    assert not should_capture(armed=False, button1=False, click_mode=False)
    assert not should_capture(armed=False, button1=True, click_mode=False)
    session = RecorderSession()
    assert not session.add_point(10, 10, button1=False)
    assert not session.add_point(12, 12, button1=True)
    assert not session.has_ink()
    assert not session.grab_pointer


def test_space_clears_and_rearms():
    session = RecorderSession()
    session.handle_space()
    assert session.armed
    assert session.grab_pointer
    session.add_point(1, 1, button1=False)
    session.add_point(9, 4, button1=False)
    assert session.has_ink()
    session.handle_space()
    assert session.armed
    assert session.grab_pointer
    assert not session.has_ink()
    session.add_point(2, 2, button1=False)
    session.add_point(11, 8, button1=False)
    assert session.has_ink()


def test_enter_saves_svg(tmp_path):
    session = RecorderSession()
    session.handle_space()
    session.add_point(4, 20, button1=False)
    session.add_point(40, 8, button1=False)
    session.add_point(80, 22, button1=False)
    assert session.handle_enter()
    assert not session.armed
    assert not session.grab_pointer
    path = tmp_path / "jane.svg"
    session.write_svg(path)
    text = path.read_text(encoding="utf-8")
    assert text.lstrip().startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in text
    assert "<path " in text
    assert "M " in text
    assert path.suffix == ".svg"


def test_enter_without_ink_does_not_save():
    session = RecorderSession()
    session.handle_space()
    session.add_point(1, 1, button1=False)  # single point is not ink
    assert not session.handle_enter()
    assert session.armed


def test_click_mode_requires_button():
    assert not should_capture(armed=True, button1=False, click_mode=True)
    assert should_capture(armed=True, button1=True, click_mode=True)
    session = RecorderSession(click_mode=True)
    session.handle_space()
    assert not session.add_point(1, 1, button1=False)
    assert session.add_point(1, 1, button1=True)
    assert session.add_point(8, 3, button1=True)


def test_stroke_mode_labels_have_no_hover_goal():
    idle = stroke_mode_label(armed=False)
    assert "Space" in idle
    assert "hover" not in idle.lower()
    live = stroke_mode_label(armed=True, has_ink=False)
    assert "without clicking" in live
    assert "hover" not in live.lower()


def test_strokes_to_svg_is_svg():
    svg = strokes_to_svg([[(0, 0), (10, 4), (20, 0)]])
    assert svg.startswith("<svg")
    assert 'fill="#0d0d33"' in svg
    assert "stroke-width" not in svg
    assert " Z" in svg


def test_pad_mapper_relative_deltas_stay_on_pad():
    mapper = PadMapper(100, 80)
    start = mapper.pen
    assert mapper.feed(1000, 2000) is None  # origin only
    point = mapper.feed(1010, 2008)
    assert point is not None
    assert point[0] == start[0] + 10
    assert point[1] == start[1] + 8


def test_pad_mapper_absolute_uses_glass_coords():
    mapper = PadMapper(100, 80)
    mapper.absolute = True
    point = mapper.feed(40, 30, on_glass=True)
    assert point == (40, 30)


def test_none_legacy_event_is_ignored():
    from omepreview.draw import legacy_event_usable

    assert not legacy_event_usable(None)

    class _NoType:
        pass

    assert not legacy_event_usable(_NoType())

    class _HasType:
        type = 1

    assert legacy_event_usable(_HasType())


def test_contact_up_ends_stroke():
    session = RecorderSession()
    session.handle_space()
    assert session.apply_abs("down", 10, 10)
    assert session.apply_abs("move", 24, 14)
    assert session.drawing
    assert session.has_ink()
    assert session.apply_abs("up")
    assert not session.drawing
    assert session.has_ink()


def test_new_contact_at_different_abs_starts_disconnected_stroke():
    session = RecorderSession(pad_size=(200.0, 100.0))
    session.handle_space()
    session.apply_abs("down", 12, 18)
    session.apply_abs("move", 40, 22)
    session.apply_abs("up")
    session.apply_abs("down", 160, 80)
    session.apply_abs("move", 170, 70)
    session.apply_abs("up")
    inked = [s for s in session.strokes if len(s) >= 2]
    assert len(inked) == 2
    first, second = inked
    assert (first[0].x, first[0].y) == (12.0, 18.0)
    assert (second[0].x, second[0].y) == (160.0, 80.0)
    # No connecting segment from the last ink point to the new contact.
    assert abs(first[-1][0] - second[0][0]) > 80
    svg = strokes_to_svg(session.strokes)
    assert svg.count("M ") == 2


def test_click_mode_ignores_abs_contacts():
    session = RecorderSession(click_mode=True)
    session.handle_space()
    assert not session.apply_abs("down", 10, 10)
    assert not session.has_ink()


def test_higher_pressure_wider_segment():
    lo = pressure_to_radius(0, (0, 255))
    hi = pressure_to_radius(255, (0, 255))
    mid = pressure_to_radius(128, (0, 255))
    assert lo == HAIRLINE_RADIUS
    assert hi == MAX_RADIUS
    assert lo < mid < hi
    thin = [
        InkPoint(0, 0, lo),
        InkPoint(30, 0, lo),
        InkPoint(60, 0, lo),
    ]
    fat = [
        InkPoint(0, 0, hi),
        InkPoint(30, 0, hi),
        InkPoint(60, 0, hi),
    ]
    def _width(pts):
        outline = ribbon_outline(pts)
        ys = [y for x, y in outline if 20 < x < 40]
        return max(ys) - min(ys)

    assert _width(fat) > _width(thin) + 2


def test_zero_min_pressure_is_hairline():
    assert pressure_to_radius(0, (0, 255)) == HAIRLINE_RADIUS
    assert pressure_to_radius(10, (10, 200)) == HAIRLINE_RADIUS
    assert pressure_to_radius(99, None) == FALLBACK_RADIUS
    assert pressure_to_radius(None, None) == FALLBACK_RADIUS
    session = RecorderSession()
    session.handle_space()
    session.add_point(0, 0, radius=HAIRLINE_RADIUS)
    session.add_point(10, 0, radius=HAIRLINE_RADIUS)
    assert session.strokes[0][-1].radius <= HAIRLINE_RADIUS + 0.2


def test_svg_contains_varying_geometry():
    stroke = [
        InkPoint(0, 20, HAIRLINE_RADIUS),
        InkPoint(40, 20, HAIRLINE_RADIUS),
        InkPoint(80, 20, MAX_RADIUS),
        InkPoint(120, 20, MAX_RADIUS),
    ]
    svg = strokes_to_svg([stroke])
    assert 'fill="#0d0d33"' in svg
    assert "stroke-width" not in svg
    outline = ribbon_outline(stroke)
    ys_thin = [y for x, y in outline if 35 <= x <= 45]
    ys_fat = [y for x, y in outline if 75 <= x <= 85]
    assert ys_thin and ys_fat
    assert (max(ys_fat) - min(ys_fat)) > (max(ys_thin) - min(ys_thin)) + 3
    session = RecorderSession()
    session.handle_space()
    pr = (0, 100)
    session.apply_abs("down", 0, 10, pressure=0, pressure_range=pr)
    session.apply_abs("move", 20, 10, pressure=0, pressure_range=pr)
    session.apply_abs("move", 40, 10, pressure=100, pressure_range=pr)
    session.apply_abs("move", 60, 10, pressure=100, pressure_range=pr)
    radii = [p.radius for p in session.strokes[0]]
    assert radii[-1] > radii[0]
    assert " Z" in strokes_to_svg(session.strokes)

