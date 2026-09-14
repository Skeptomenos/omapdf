"""Trackpad signature capture policy tests."""

from omepreview.trackpad_sig import (
    PadMapper,
    RecorderSession,
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
    assert "stroke-linecap=\"round\"" in svg


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
