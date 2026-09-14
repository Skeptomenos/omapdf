"""Absolute trackpad (evdev) mapping tests."""

import os

from omepreview.abs_pad import (
    ABS_MT_POSITION_X,
    ABS_MT_POSITION_Y,
    ABS_MT_TRACKING_ID,
    ABS_X,
    ABS_Y,
    BTN_TOOL_FINGER,
    BTN_TOUCH,
    EV_ABS,
    EV_KEY,
    EV_SYN,
    EVENT_SIZE,
    EVIOCGRAB,
    SYN_REPORT,
    AbsPadWatcher,
    AbsRange,
    EvdevAbsDevice,
    MtParser,
    map_abs_to_pad,
    pack_input_event,
)
from omepreview.trackpad_sig import RecorderSession, strokes_to_svg


def _feed(parser: MtParser, *events):
    out = []
    for etype, code, value in events:
        out.extend(parser.feed(etype, code, value))
    return out


def test_map_abs_range_onto_pad():
    axes = AbsRange(x_min=0, x_max=2000, y_min=0, y_max=1000)
    assert map_abs_to_pad(0, 0, axes, 200, 100) == (0.0, 0.0)
    assert map_abs_to_pad(2000, 1000, axes, 200, 100) == (200.0, 100.0)
    assert map_abs_to_pad(1000, 500, axes, 200, 100) == (100.0, 50.0)
    clamped = map_abs_to_pad(-50, 5000, axes, 200, 100)
    assert clamped == (0.0, 100.0)


def test_mt_tracking_id_lift_emits_up():
    parser = MtParser()
    events = _feed(
        parser,
        (EV_ABS, ABS_MT_TRACKING_ID, 7),
        (EV_ABS, ABS_MT_POSITION_X, 100),
        (EV_ABS, ABS_MT_POSITION_Y, 200),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_POSITION_X, 110),
        (EV_ABS, ABS_MT_POSITION_Y, 205),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_TRACKING_ID, -1),
        (EV_SYN, SYN_REPORT, 0),
    )
    kinds = [e.kind for e in events]
    assert kinds == ["down", "move", "up"]
    assert events[0].x == 100 and events[0].y == 200
    assert events[1].x == 110 and events[1].y == 205


def test_btn_touch_abs_xy_contact():
    parser = MtParser()
    events = _feed(
        parser,
        (EV_KEY, BTN_TOUCH, 1),
        (EV_KEY, BTN_TOOL_FINGER, 1),
        (EV_ABS, ABS_X, 40),
        (EV_ABS, ABS_Y, 60),
        (EV_SYN, SYN_REPORT, 0),
        (EV_KEY, BTN_TOUCH, 0),
        (EV_KEY, BTN_TOOL_FINGER, 0),
        (EV_SYN, SYN_REPORT, 0),
    )
    assert [e.kind for e in events] == ["down", "up"]
    assert events[0].x == 40 and events[0].y == 60


def test_parser_and_session_new_contact_is_disconnected():
    parser = MtParser()
    session = RecorderSession(pad_size=(200.0, 100.0))
    session.handle_space()
    axes = AbsRange(0, 1000, 0, 500)
    raw = [
        (EV_ABS, ABS_MT_TRACKING_ID, 1),
        (EV_ABS, ABS_MT_POSITION_X, 100),
        (EV_ABS, ABS_MT_POSITION_Y, 50),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_POSITION_X, 140),
        (EV_ABS, ABS_MT_POSITION_Y, 55),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_TRACKING_ID, -1),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_TRACKING_ID, 2),
        (EV_ABS, ABS_MT_POSITION_X, 800),
        (EV_ABS, ABS_MT_POSITION_Y, 400),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_POSITION_X, 820),
        (EV_ABS, ABS_MT_POSITION_Y, 390),
        (EV_SYN, SYN_REPORT, 0),
        (EV_ABS, ABS_MT_TRACKING_ID, -1),
        (EV_SYN, SYN_REPORT, 0),
    ]
    for etype, code, value in raw:
        for ev in parser.feed(etype, code, value):
            if ev.kind == "up":
                session.apply_abs("up")
            else:
                x, y = map_abs_to_pad(ev.x, ev.y, axes, session.pad_w, session.pad_h)
                session.apply_abs(ev.kind, x, y)
    inked = [s for s in session.strokes if len(s) >= 2]
    assert len(inked) == 2
    assert inked[0][0] == map_abs_to_pad(100, 50, axes, 200, 100)
    assert inked[1][0] == map_abs_to_pad(800, 400, axes, 200, 100)
    assert strokes_to_svg(session.strokes).count("M ") == 2


def test_evdev_device_reads_packed_events_from_pipe():
    r, w = os.pipe()
    blob = b"".join(
        pack_input_event(etype, code, value)
        for etype, code, value in (
            (EV_ABS, ABS_MT_TRACKING_ID, 3),
            (EV_ABS, ABS_MT_POSITION_X, 10),
            (EV_ABS, ABS_MT_POSITION_Y, 20),
            (EV_SYN, SYN_REPORT, 0),
            (EV_ABS, ABS_MT_TRACKING_ID, -1),
            (EV_SYN, SYN_REPORT, 0),
        )
    )
    os.write(w, blob)
    os.close(w)
    assert EVENT_SIZE == 24 or EVENT_SIZE in (16, 32)
    dev = EvdevAbsDevice(
        path="pipe",
        fd=r,
        name="fake",
        axes=AbsRange(0, 100, 0, 100),
        has_mt=True,
    )
    try:
        contacts = dev.read_contacts()
    finally:
        dev.close()
    assert [c.kind for c in contacts] == ["down", "up"]
    assert contacts[0].x == 10 and contacts[0].y == 20


class _IoctlLog:
    def __init__(self):
        self.calls: list[int] = []
        self.error: OSError | None = None

    def __call__(self, fd, req, arg):
        assert req == EVIOCGRAB
        if self.error is not None:
            raise self.error
        self.calls.append(int(arg))


def _pipe_device(ioctl, *, retain_write: bool = False) -> tuple[EvdevAbsDevice, int | None]:
    r, w = os.pipe()
    if not retain_write:
        os.close(w)
        w = None
    dev = EvdevAbsDevice(
        path="pipe",
        fd=r,
        name="fake-touchpad",
        axes=AbsRange(0, 100, 0, 100),
        has_mt=True,
        ioctl=ioctl,
    )
    return dev, w


def test_eviocgrab_ioctl_number():
    # linux/input.h: _IOW('E', 0x90, int) == 0x40044590 on this ABI
    assert EVIOCGRAB == 0x40044590


def test_grab_ungrab_lifecycle():
    log = _IoctlLog()
    dev, _ = _pipe_device(log)
    assert not dev.grabbed
    assert dev.grab()
    assert dev.grabbed
    assert log.calls == [1]
    assert dev.grab()  # idempotent — no second ioctl
    assert log.calls == [1]
    dev.ungrab()
    assert not dev.grabbed
    assert log.calls == [1, 0]
    dev.ungrab()  # idempotent
    assert log.calls == [1, 0]
    dev.close()


def test_close_ungrabs():
    log = _IoctlLog()
    dev, _ = _pipe_device(log)
    assert dev.grab()
    dev.close()
    assert not dev.grabbed
    assert log.calls == [1, 0]
    assert dev.fd == -1


def test_space_rearm_ungrabs_then_grabs():
    """Space clear/re-arm: drop the old grab, then grab the new fd."""
    log = _IoctlLog()
    first, _ = _pipe_device(log)
    assert first.grab()
    first.close()
    second, _ = _pipe_device(log)
    assert second.grab()
    second.close()
    assert log.calls == [1, 0, 1, 0]


def test_error_path_ungrabs():
    log = _IoctlLog()
    dev, _ = _pipe_device(log)
    try:
        assert dev.grab()
        raise RuntimeError("boom")
    except RuntimeError:
        pass
    finally:
        dev.close()
    assert not dev.grabbed
    assert log.calls == [1, 0]


def test_grab_failure_leaves_ungrabbed():
    log = _IoctlLog()
    log.error = OSError(16, "busy")  # EBUSY
    dev, _ = _pipe_device(log)
    assert not dev.grab()
    assert not dev.grabbed
    assert log.calls == []
    dev.close()


def test_watcher_grabs_on_start_ungrabs_on_stop():
    log = _IoctlLog()
    dev, write_fd = _pipe_device(log, retain_write=True)
    watcher = AbsPadWatcher(dev, lambda _c: None, idle_add=lambda *_a: False)
    try:
        assert watcher.start(exclusive=True) is True
        assert log.calls == [1]
        assert dev.grabbed
        watcher.stop()
        watcher.stop()  # idempotent
        assert not dev.grabbed
        assert log.calls == [1, 0]
    finally:
        if write_fd is not None:
            os.close(write_fd)


def test_watcher_exclusive_false_does_not_grab():
    log = _IoctlLog()
    dev, write_fd = _pipe_device(log, retain_write=True)
    watcher = AbsPadWatcher(dev, lambda _c: None, idle_add=lambda *_a: False)
    try:
        assert watcher.start(exclusive=False) is False
        assert log.calls == []
        watcher.stop()
        assert log.calls == []
    finally:
        if write_fd is not None:
            os.close(write_fd)


def test_grab_does_not_ioctl_keyboard_fd():
    """Only the touchpad fd is grabbed; a keyboard node is left alone."""
    pad_log = _IoctlLog()
    kbd_log = _IoctlLog()
    pad, _ = _pipe_device(pad_log)
    keyboard, _ = _pipe_device(kbd_log)
    try:
        assert pad.grab()
        # Recorder never calls grab() on a keyboard node (no ABS axes).
        assert pad_log.calls == [1]
        assert kbd_log.calls == []
    finally:
        pad.close()
        keyboard.close()
    assert pad_log.calls == [1, 0]
    assert kbd_log.calls == []
