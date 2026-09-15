"""Adwaita color-scheme drives chrome off Omarchy; PDF paper stays white."""

from pathlib import Path

from omepreview.theme import (
    PORTAL_PREFER_DARK,
    PORTAL_PREFER_LIGHT,
    adwaita_theme_for_scheme,
    desk_is_light,
    scheme_is_dark,
)


def test_scheme_portal_and_gnome_prefer():
    assert scheme_is_dark(portal=PORTAL_PREFER_DARK, gnome="prefer-light") is True
    assert scheme_is_dark(portal=PORTAL_PREFER_LIGHT, gnome="prefer-dark") is False
    assert scheme_is_dark(portal=None, gnome="prefer-dark") is True
    assert scheme_is_dark(portal=None, gnome="prefer-light") is False
    assert scheme_is_dark(portal=0, gnome="default", gtk_prefer_dark=True) is True
    assert scheme_is_dark(portal=0, gnome="default", gtk_prefer_dark=False) is False


def test_adwaita_theme_flips_with_scheme():
    assert adwaita_theme_for_scheme("Adwaita-dark", dark=False) == "Adwaita"
    assert adwaita_theme_for_scheme("Adwaita", dark=True) == "Adwaita-dark"
    assert adwaita_theme_for_scheme("Adwaita:dark", dark=False) == "Adwaita"
    assert adwaita_theme_for_scheme("Yaru-blue", dark=True) == "Yaru-blue"


def test_desk_luminance_picks_light_vs_dark_factor():
    assert desk_is_light((0.965, 0.961, 0.957)) is True
    assert desk_is_light((0.208, 0.208, 0.208)) is False


def test_editorial_css_uses_adwaita_tokens_and_styles_popovers():
    src = (
        Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def _editorial_css") : src.index("def _overlay_rail_css")]
    assert "@theme_bg_color" in body
    assert "@theme_fg_color" in body
    assert "popover.background" in body
    assert "scrolledwindow.omapdf-thumb-rail" in body
    assert "box.omapdf-overlay-toolbar" in body
    assert "border: none" in body
    assert "border: 2px" not in body
    assert "#" not in body.replace("def _editorial_css", "")
    apply = src[src.index("def apply_chrome") : src.index("chrome_theme.watch_appearance")]
    assert "load_omarchy_palette" in apply
    assert "css_defines" in apply
    assert "blob = prefix + _editorial_css" in apply
    assert "blob += WINDOW_CONTROLS_CSS" in apply
    assert "css.load_from_data(blob)" in apply
    assert "css.load_from_data(WINDOW_CONTROLS_CSS)" not in src
    assert "sync_gtk_appearance" in apply
    assert "desk_is_light" in apply
    assert "applying[\"again\"]" in apply
    assert "GLib.idle_add(apply_chrome)" in apply
    assert "ctx.set_source_rgb(1, 1, 1)" in src
    tail = src[src.index("chrome_theme.watch_appearance") : src.index('win.connect("realize"')]
    assert "watch_theme_set" in tail
