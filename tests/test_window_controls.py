"""window_controls detection and OMEPREVIEW_WINDOW_CONTROLS override."""

import os
from unittest import mock

from omepreview import window_controls as wc


def test_override_force_on():
    with mock.patch.dict(os.environ, {"OMEPREVIEW_WINDOW_CONTROLS": "1"}, clear=True):
        assert wc.window_controls_enabled() is True


def test_override_force_off():
    with mock.patch.dict(os.environ, {"OMEPREVIEW_WINDOW_CONTROLS": "0"}, clear=True):
        assert wc.window_controls_enabled() is False


def test_legacy_omapdf_alias_still_works():
    with mock.patch.dict(os.environ, {"OMAPDF_WINDOW_CONTROLS": "1"}, clear=True):
        assert wc.window_controls_enabled() is True
    with mock.patch.dict(os.environ, {"OMAPDF_WINDOW_CONTROLS": "0"}, clear=True):
        assert wc.window_controls_enabled() is False


def test_new_name_wins_over_legacy_alias():
    env = {"OMEPREVIEW_WINDOW_CONTROLS": "0", "OMAPDF_WINDOW_CONTROLS": "1"}
    with mock.patch.dict(os.environ, env, clear=True):
        assert wc.window_controls_enabled() is False


def test_hyprland_hides_controls():
    env = {"OMEPREVIEW_WINDOW_CONTROLS": "", "HYPRLAND_INSTANCE_SIGNATURE": "abc"}
    with mock.patch.dict(os.environ, env, clear=True):
        assert wc.detect_omarchy_environment() is True
        assert wc.window_controls_enabled() is False


def test_non_omarchy_shows_controls():
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch.object(wc, "detect_omarchy_environment", return_value=False):
            assert wc.window_controls_enabled() is True


def test_omarchy_desktop_hides_controls():
    with mock.patch.dict(
        os.environ,
        {"XDG_CURRENT_DESKTOP": "Hyprland:omarchy"},
        clear=True,
    ):
        assert wc.detect_omarchy_environment() is True
