"""Safe-popover gateway: liveness, mapped-autohide skip, grep gate."""

from pathlib import Path

import pytest

from omepreview import popover_safe
from omepreview.popover_safe import (
    popover_busy,
    popover_try_popdown,
    popover_try_popup,
    popover_try_set_autohide,
)
from omepreview.view_gestures import popover_allows


@pytest.fixture(autouse=True)
def _clear_popover_busy():
    popover_safe._open.clear()
    yield
    popover_safe._open.clear()


class _Fake:
    def __init__(self, *, ptr="0xabc", parent=True, realized=False, surface=None):
        self.__gpointer__ = ptr
        self._parent = object() if parent else None
        self._realized = realized
        self._surface = surface
        self.calls: list = []
        self._closed_cb = None

    def get_parent(self):
        return self._parent

    def get_realized(self):
        return self._realized

    def get_surface(self):
        return self._surface

    def popup(self):
        self.calls.append("popup")
        self._realized = True
        self._surface = object()

    def popdown(self):
        self.calls.append("popdown")
        self._realized = False
        self._surface = None
        if self._closed_cb is not None:
            self._closed_cb(self)

    def set_autohide(self, value):
        self.calls.append(("autohide", value))

    def connect(self, signal, cb, *a, **k):
        if signal == "closed":
            self._closed_cb = cb
        return 1


def test_try_popup_skips_null_and_orphan():
    dead = _Fake(ptr="NULL")
    assert popover_try_popup(dead) is False
    assert dead.calls == []
    orphan = _Fake(parent=False)
    assert popover_try_popup(orphan) is False
    assert orphan.calls == []
    live = _Fake()
    assert popover_try_popup(live) is True
    assert "popup" in live.calls


def test_try_popup_skips_realized_without_surface():
    zombie = _Fake(realized=True, surface=None)
    assert popover_allows(zombie, "popup") is False
    assert popover_try_popup(zombie) is False
    assert zombie.calls == []


def test_try_popdown_requires_surface():
    unrealized = _Fake()
    assert popover_try_popdown(unrealized) is False
    zombie = _Fake(realized=True, surface=None)
    assert popover_try_popdown(zombie) is False
    mapped = _Fake(realized=True, surface=object())
    assert popover_try_popdown(mapped) is True
    assert "popdown" in mapped.calls


def test_try_set_autohide_only_before_mapped():
    construct = _Fake()
    assert popover_try_set_autohide(construct, True) is True
    assert construct.calls == [("autohide", True)]
    mapped = _Fake(realized=True, surface=object())
    assert popover_try_set_autohide(mapped, False) is False
    assert mapped.calls == []
    zombie = _Fake(realized=True, surface=None)
    assert popover_try_set_autohide(zombie, False) is False
    assert zombie.calls == []


def test_gui_files_have_no_direct_popover_calls():
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview"
    forbidden = []
    for name in ("gui.py", "gui_pages.py"):
        for i, line in enumerate((src / name).read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if ".set_autohide(" in stripped or ".popdown(" in stripped or ".popup(" in stripped:
                forbidden.append(f"{name}:{i}:{line.strip()}")
    assert forbidden == [], "direct popover calls must go through popover_safe:\n" + "\n".join(
        forbidden
    )


def test_popover_busy_sets_on_popup_and_clears_on_closed():
    widget = _Fake()
    assert popover_busy() is False
    assert popover_try_popup(widget) is True
    assert popover_busy() is True
    assert popover_try_popdown(widget) is True
    assert popover_busy() is False


def test_page_menu_keeps_parent_and_actions():
    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "omepreview"
        / "gui_pages.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def show_menu") : src.index("def act_rotate_cw")]
    assert "popover.set_parent(host)" in body
    assert "popover_try_popup(popover)" in body
    assert "popover.connect(\"closed\"" not in src
    assert "popover.insert_action_group(\"page\"" in src
    assert "side_list.insert_action_group(\"page\"" in src
    assert ".set_autohide(" not in src


def test_reorder_drop_swallows_illegal_after():
    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "omepreview"
        / "gui_pages.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def on_reorder_drop") : src.index("drop_target.connect")]
    assert "if after != 0 and after in pages:" in body
    assert "except OpError:" in body
    assert "traceback" not in body.lower()
