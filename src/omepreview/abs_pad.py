"""Absolute trackpad coordinates from evdev (stdlib).

GTK / libinput pointer events are relative: after a finger lift the OS
cursor stays put, so the next contact continues from the last ink point.
While the recorder is armed we read the touchpad node directly
(ABS_MT_POSITION_* or ABS_X/ABS_Y) and map that range onto the on-screen
pad. Relative pointer motion is fallback only when no abs axes can be
opened.

While armed we EVIOCGRAB the *touchpad* node so libinput/the compositor
do not also move the system cursor. The keyboard is never grabbed (Space
and Enter must keep working). Ungrab on save, re-arm, close, and errors.
"""

from __future__ import annotations

import array
import errno
import fcntl
import glob
import os
import select
import struct
import threading
from dataclasses import dataclass, field

# linux/input-event-codes.h
EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0
SYN_MT_REPORT = 2
ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
BTN_TOUCH = 0x14A
BTN_TOOL_FINGER = 0x145
BTN_TOOL_PEN = 0x140
INPUT_PROP_POINTER = 0x00
INPUT_PROP_DIRECT = 0x01
INPUT_PROP_BUTTONPAD = 0x02

# struct input_event: timeval + type + code + value. 24 bytes on 64-bit.
_EVENT = struct.Struct("llHHi")
EVENT_SIZE = _EVENT.size

# struct input_absinfo: value, minimum, maximum, fuzz, flat, resolution
_ABSINFO = struct.Struct("iiiiii")


def _ioc_read(nr: int, size: int) -> int:
    return (2 << 30) | (ord("E") << 8) | nr | (size << 16)


def _ioc_write(nr: int, size: int) -> int:
    return (1 << 30) | (ord("E") << 8) | nr | (size << 16)


# linux/input.h: EVIOCGRAB _IOW('E', 0x90, int) — exclusive client.
# Kernel treats a non-zero arg as grab, zero as ungrab. Touchpad fd only.
EVIOCGRAB = _ioc_write(0x90, struct.calcsize("i"))


def _EVIOCGNAME(n: int) -> int:
    return _ioc_read(0x06, n)


def _EVIOCGPROP(n: int) -> int:
    return _ioc_read(0x09, n)


def _EVIOCGBIT(ev: int, n: int) -> int:
    return _ioc_read(0x20 + ev, n)


def _EVIOCGABS(code: int) -> int:
    return _ioc_read(0x40 + code, _ABSINFO.size)


def _bit(buf: bytes, bit: int) -> bool:
    byte = bit // 8
    if byte >= len(buf):
        return False
    return bool(buf[byte] & (1 << (bit % 8)))


def _ioctl_bytes(fd: int, req: int, n: int) -> bytes | None:
    buf = array.array("B", b"\x00" * n)
    try:
        fcntl.ioctl(fd, req, buf, True)
    except OSError:
        return None
    return buf.tobytes()


def _ioctl_name(fd: int) -> str:
    raw = _ioctl_bytes(fd, _EVIOCGNAME(256), 256)
    if not raw:
        return ""
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _ioctl_abs(fd: int, code: int) -> tuple[int, int] | None:
    buf = array.array("B", b"\x00" * _ABSINFO.size)
    try:
        fcntl.ioctl(fd, _EVIOCGABS(code), buf, True)
    except OSError:
        return None
    _value, minimum, maximum, _fuzz, _flat, _res = _ABSINFO.unpack(buf.tobytes())
    if maximum <= minimum:
        return None
    return int(minimum), int(maximum)


def unpack_input_event(data: bytes) -> tuple[int, int, int]:
    """Return (type, code, value) from one input_event blob."""
    _sec, _usec, etype, code, value = _EVENT.unpack(data)
    return int(etype), int(code), int(value)


def pack_input_event(etype: int, code: int, value: int) -> bytes:
    return _EVENT.pack(0, 0, etype, code, value)


def _as_tracking_id(value: int) -> int:
    # Lift is -1; some readers deliver it as unsigned 32-bit.
    if value < 0 or value == 0xFFFFFFFF:
        return -1
    return value


@dataclass(frozen=True)
class AbsRange:
    x_min: int
    x_max: int
    y_min: int
    y_max: int


def map_abs_to_pad(
    abs_x: float,
    abs_y: float,
    axes: AbsRange,
    pad_w: float,
    pad_h: float,
) -> tuple[float, float]:
    """Map a device abs sample onto the on-screen pad (top-left origin)."""
    dx = axes.x_max - axes.x_min
    dy = axes.y_max - axes.y_min
    if dx <= 0 or dy <= 0:
        return 0.0, 0.0
    x = (float(abs_x) - axes.x_min) / dx * pad_w
    y = (float(abs_y) - axes.y_min) / dy * pad_h
    if x < 0.0:
        x = 0.0
    elif x > pad_w:
        x = pad_w
    if y < 0.0:
        y = 0.0
    elif y > pad_h:
        y = pad_h
    return x, y


@dataclass
class ContactEvent:
    kind: str  # "down" | "move" | "up"
    x: int | None = None
    y: int | None = None


class MtParser:
    """Turn a stream of evdev (type, code, value) into contact down/move/up.

    Prefers MT protocol B (ABS_MT_SLOT + TRACKING_ID). Protocol A
    (SYN_MT_REPORT) and single-touch ABS_X/Y + BTN_TOUCH / BTN_TOOL_FINGER
    are fallbacks. Only the primary finger (slot 0) is used.
    """

    def __init__(self) -> None:
        self.slot = 0
        self.slots: dict[int, dict[str, int | None]] = {
            0: {"id": -1, "x": None, "y": None}
        }
        self.btn_touch: bool | None = None
        self.btn_finger: bool | None = None
        self.abs_x: int | None = None
        self.abs_y: int | None = None
        self.contact = False
        self.last_x: int | None = None
        self.last_y: int | None = None
        self._proto_a: list[tuple[int | None, int | None]] = []
        self._a_x: int | None = None
        self._a_y: int | None = None
        self._saw_mt = False

    def _ensure_slot(self, n: int) -> dict[str, int | None]:
        slot = self.slots.get(n)
        if slot is None:
            slot = {"id": -1, "x": None, "y": None}
            self.slots[n] = slot
        return slot

    def feed(self, etype: int, code: int, value: int) -> list[ContactEvent]:
        if etype == EV_ABS:
            if code == ABS_MT_SLOT:
                self.slot = int(value)
                self._ensure_slot(self.slot)
            elif code == ABS_MT_TRACKING_ID:
                self._saw_mt = True
                self._ensure_slot(self.slot)["id"] = _as_tracking_id(value)
            elif code == ABS_MT_POSITION_X:
                self._saw_mt = True
                self._ensure_slot(self.slot)["x"] = int(value)
                self._a_x = int(value)
            elif code == ABS_MT_POSITION_Y:
                self._saw_mt = True
                self._ensure_slot(self.slot)["y"] = int(value)
                self._a_y = int(value)
            elif code == ABS_X:
                self.abs_x = int(value)
            elif code == ABS_Y:
                self.abs_y = int(value)
        elif etype == EV_KEY:
            if code == BTN_TOUCH:
                self.btn_touch = bool(value)
            elif code == BTN_TOOL_FINGER:
                self.btn_finger = bool(value)
        elif etype == EV_SYN:
            if code == SYN_MT_REPORT:
                if self._a_x is not None or self._a_y is not None:
                    self._proto_a.append((self._a_x, self._a_y))
                self._a_x = None
                self._a_y = None
            elif code == SYN_REPORT:
                return self._flush()
        return []

    def _live_slot(self) -> dict[str, int | None] | None:
        live = None
        live_n = None
        for n, slot in self.slots.items():
            tid = slot.get("id")
            if tid is not None and tid >= 0:
                if live_n is None or n < live_n:
                    live = slot
                    live_n = n
        return live

    def _primary_xy(self) -> tuple[int | None, int | None]:
        slot = self._live_slot()
        if slot is not None:
            x = slot["x"] if slot["x"] is not None else self.abs_x
            y = slot["y"] if slot["y"] is not None else self.abs_y
            return x, y
        if self._proto_a:
            return self._proto_a[0]
        return self.abs_x, self.abs_y

    def _in_contact(self) -> bool:
        if self._live_slot() is not None:
            return True
        if self._saw_mt and self.contact:
            # Every slot has tracking_id -1: finger up, even if BTN_* lags.
            return False
        if self._proto_a:
            return True
        if self.btn_touch is True:
            return True
        if self.btn_touch is False:
            return False
        if self.btn_finger is True:
            return True
        if self.btn_finger is False:
            return False
        return False

    def _flush(self) -> list[ContactEvent]:
        in_c = self._in_contact()
        x, y = self._primary_xy()
        self._proto_a = []
        events: list[ContactEvent] = []
        if in_c and not self.contact:
            if x is None or y is None:
                return events
            self.contact = True
            self.last_x, self.last_y = x, y
            events.append(ContactEvent("down", x, y))
        elif not in_c and self.contact:
            self.contact = False
            events.append(ContactEvent("up", self.last_x, self.last_y))
        elif in_c and x is not None and y is not None:
            if x != self.last_x or y != self.last_y:
                self.last_x, self.last_y = x, y
                events.append(ContactEvent("move", x, y))
        return events


def _score_touchpad(
    *,
    name: str,
    has_mt: bool,
    has_finger: bool,
    has_touch: bool,
    has_pen: bool,
    props: bytes | None,
) -> int:
    lower = name.lower()
    if "touchscreen" in lower or "ts_" in lower:
        return 0
    if props and _bit(props, INPUT_PROP_DIRECT):
        return 0
    if has_pen and not has_finger and not has_mt:
        return 0
    if not has_mt and not has_finger:
        if "touchpad" not in lower and "trackpad" not in lower:
            return 0
    score = 0
    if has_mt:
        score += 4
    if has_finger:
        score += 4
    if has_touch:
        score += 1
    if props and _bit(props, INPUT_PROP_BUTTONPAD):
        score += 2
    if props and _bit(props, INPUT_PROP_POINTER):
        score += 1
    for needle, pts in (
        ("touchpad", 3),
        ("trackpad", 3),
        ("synaptics", 2),
        ("elan", 2),
        ("bcm5974", 2),
        ("apple", 1),
        ("dll", 1),  # Dell HID pads
    ):
        if needle in lower:
            score += pts
    return score


@dataclass
class EvdevAbsDevice:
    path: str
    fd: int
    name: str
    axes: AbsRange
    has_mt: bool
    parser: MtParser = field(default_factory=MtParser)
    grabbed: bool = False
    ioctl: object = field(default=fcntl.ioctl)
    _buf: bytearray = field(default_factory=bytearray)

    def map_point(
        self, abs_x: float, abs_y: float, pad_w: float, pad_h: float
    ) -> tuple[float, float]:
        return map_abs_to_pad(abs_x, abs_y, self.axes, pad_w, pad_h)

    def grab(self) -> bool:
        """EVIOCGRAB this touchpad so the compositor stops seeing its motion.

        Does not grab the keyboard. Idempotent. False if ioctl fails.
        """
        if self.fd < 0:
            return False
        if self.grabbed:
            return True
        try:
            self.ioctl(self.fd, EVIOCGRAB, 1)
        except OSError:
            self.grabbed = False
            return False
        self.grabbed = True
        return True

    def ungrab(self) -> None:
        """Drop EVIOCGRAB. Idempotent; safe on a closed or never-grabbed fd."""
        if not self.grabbed:
            return
        try:
            if self.fd >= 0:
                self.ioctl(self.fd, EVIOCGRAB, 0)
        except OSError:
            pass
        self.grabbed = False

    def read_contacts(self) -> list[ContactEvent]:
        try:
            data = os.read(self.fd, EVENT_SIZE * 64)
        except BlockingIOError:
            return []
        except OSError:
            return []
        if not data:
            return []
        self._buf.extend(data)
        out: list[ContactEvent] = []
        while len(self._buf) >= EVENT_SIZE:
            chunk = bytes(self._buf[:EVENT_SIZE])
            del self._buf[:EVENT_SIZE]
            etype, code, value = unpack_input_event(chunk)
            out.extend(self.parser.feed(etype, code, value))
        return out

    def close(self) -> None:
        """Ungrab then close. Always ungrabs, even if close fails."""
        try:
            self.ungrab()
        finally:
            fd, self.fd = self.fd, -1
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


@dataclass
class AbsProbe:
    device: EvdevAbsDevice | None
    permission_denied: bool
    tried: int = 0
    names: tuple[str, ...] = ()


def _open_candidate(path: str) -> tuple[EvdevAbsDevice | None, bool]:
    """Return (device, permission_denied)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        return None, exc.errno in (errno.EACCES, errno.EPERM)
    try:
        ev_bits = _ioctl_bytes(fd, _EVIOCGBIT(0, 32), 32)
        if not ev_bits or not _bit(ev_bits, EV_ABS):
            os.close(fd)
            return None, False
        abs_bits = _ioctl_bytes(fd, _EVIOCGBIT(EV_ABS, 64), 64) or b""
        has_mt = _bit(abs_bits, ABS_MT_POSITION_X) and _bit(
            abs_bits, ABS_MT_POSITION_Y
        )
        has_st = _bit(abs_bits, ABS_X) and _bit(abs_bits, ABS_Y)
        if not has_mt and not has_st:
            os.close(fd)
            return None, False
        key_bits = _ioctl_bytes(fd, _EVIOCGBIT(EV_KEY, 96), 96) or b""
        props = _ioctl_bytes(fd, _EVIOCGPROP(8), 8)
        name = _ioctl_name(fd)
        has_finger = _bit(key_bits, BTN_TOOL_FINGER)
        has_touch = _bit(key_bits, BTN_TOUCH)
        has_pen = _bit(key_bits, BTN_TOOL_PEN)
        score = _score_touchpad(
            name=name,
            has_mt=has_mt,
            has_finger=has_finger,
            has_touch=has_touch,
            has_pen=has_pen,
            props=props,
        )
        if score <= 0:
            os.close(fd)
            return None, False
        if has_mt:
            xr = _ioctl_abs(fd, ABS_MT_POSITION_X)
            yr = _ioctl_abs(fd, ABS_MT_POSITION_Y)
        else:
            xr = yr = None
        if xr is None or yr is None:
            xr = _ioctl_abs(fd, ABS_X)
            yr = _ioctl_abs(fd, ABS_Y)
        if xr is None or yr is None:
            os.close(fd)
            return None, False
        axes = AbsRange(xr[0], xr[1], yr[0], yr[1])
        dev = EvdevAbsDevice(
            path=path, fd=fd, name=name or path, axes=axes, has_mt=has_mt
        )
        # Stash score on the instance for the picker.
        dev._score = score  # type: ignore[attr-defined]
        return dev, False
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        return None, False


def probe_abs_touchpad(paths: list[str] | None = None) -> AbsProbe:
    """Open the best abs touchpad. Does not grab; arming does."""
    if paths is None:
        paths = sorted(glob.glob("/dev/input/event*"))
    denied = False
    tried = 0
    best: EvdevAbsDevice | None = None
    best_score = 0
    names: list[str] = []
    for path in paths:
        tried += 1
        dev, perm = _open_candidate(path)
        if perm:
            denied = True
        if dev is None:
            continue
        names.append(dev.name)
        score = int(getattr(dev, "_score", 1))
        if best is None or score > best_score:
            if best is not None:
                best.close()
            best = dev
            best_score = score
        else:
            dev.close()
    if best is not None:
        denied = False
    return AbsProbe(
        device=best,
        permission_denied=denied and best is None,
        tried=tried,
        names=tuple(names),
    )


class AbsPadWatcher:
    """Background reader; exclusive-grabs the touchpad while running.

    `idle_add` marshals contacts onto the GTK thread. Keyboard fds are
    never opened or grabbed.
    """

    def __init__(self, device: EvdevAbsDevice, on_contacts, *, idle_add) -> None:
        self.device = device
        self._on_contacts = on_contacts
        self._idle_add = idle_add
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="omepreview-abs-pad", daemon=True
        )
        self._started = False
        self._cleaned = False

    def start(self, *, exclusive: bool = True) -> bool:
        """Read the pad. exclusive=True EVIOCGRAB so the cursor stays put."""
        grabbed = False
        try:
            if exclusive:
                grabbed = self.device.grab()
            try:
                os.set_blocking(self.device.fd, False)
            except OSError:
                pass
            self._thread.start()
            self._started = True
            return grabbed
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """Ungrab and close. Idempotent; safe if start() never ran."""
        self._stop.set()
        if self._started:
            self._thread.join(timeout=1.0)
            self._started = False
        self._cleanup_device()

    def _cleanup_device(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            self.device.ungrab()
        finally:
            self.device.close()

    def _run(self) -> None:
        fd = self.device.fd
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.15)
            except (OSError, ValueError):
                break
            if self._stop.is_set():
                break
            if not ready:
                continue
            try:
                contacts = self.device.read_contacts()
            except OSError:
                break
            if contacts:
                self._idle_add(self._deliver, contacts)

    def _deliver(self, contacts: list[ContactEvent]) -> bool:
        if self._stop.is_set():
            return False
        try:
            self._on_contacts(contacts)
        except Exception:
            # Never traceback-spam from a motion callback.
            pass
        return False


INPUT_GROUP_HINT = (
    "Absolute pad mapping reads /dev/input/event* (evdev). "
    "A local graphical seat usually has logind ACLs; if open() fails with "
    "PermissionError, add your user to the input group and re-login: "
    "sudo usermod -aG input $USER"
)
