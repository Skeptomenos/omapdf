"""Adwaita / Omarchy color-scheme for editor chrome.

Omarchy's ``omarchy-theme-set-gnome`` writes both
``org.gnome.desktop.interface color-scheme`` (prefer-dark / prefer-light)
and ``gtk-theme`` (Adwaita / Adwaita-dark). The freedesktop portal
``org.freedesktop.appearance color-scheme`` is the same switch GTK 4 reads
(0 = no preference, 1 = prefer dark, 2 = prefer light).

``gtk-application-prefer-dark-theme`` alone cannot lighten a process that
already has ``gtk-theme-name=Adwaita-dark`` — that is why rails stayed
dark on a light Omarchy desktop. Sync theme name + prefer-dark, then let
editorial CSS derive from ``@theme_bg_color`` / ``@theme_fg_color``.

The PDF page is not themed: cairo still paints white paper.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

PORTAL_NO_PREFERENCE = 0
PORTAL_PREFER_DARK = 1
PORTAL_PREFER_LIGHT = 2

_WATCH_KEEPALIVE: list = []


def scheme_is_dark(
    *,
    portal: int | None = None,
    gnome: str | None = None,
    gtk_prefer_dark: bool = False,
) -> bool:
    """Resolve dark vs light. Explicit portal/GNOME prefer-* win."""
    if portal == PORTAL_PREFER_DARK:
        return True
    if portal == PORTAL_PREFER_LIGHT:
        return False
    if gnome == "prefer-dark":
        return True
    if gnome == "prefer-light":
        return False
    return bool(gtk_prefer_dark)


def desk_is_light(bg: tuple[float, float, float]) -> bool:
    """Pick the editorial desk shade from actual Adwaita bg luminance."""
    return (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) >= 0.5


def adwaita_theme_for_scheme(current: str | None, dark: bool) -> str:
    """Keep non-Adwaita names; flip Adwaita ↔ Adwaita-dark with the scheme."""
    name = (current or "Adwaita").strip() or "Adwaita"
    key = name.lower().replace(" ", "")
    if key in {"adwaita", "adwaita-dark", "adwaita:dark"}:
        return "Adwaita-dark" if dark else "Adwaita"
    return name


def read_gnome_color_scheme() -> str | None:
    try:
        return Gio.Settings.new("org.gnome.desktop.interface").get_string(
            "color-scheme"
        )
    except Exception:
        return None


def read_gnome_gtk_theme() -> str | None:
    try:
        value = Gio.Settings.new("org.gnome.desktop.interface").get_string(
            "gtk-theme"
        )
        return value or None
    except Exception:
        return None


def read_portal_color_scheme() -> int | None:
    """``org.freedesktop.appearance color-scheme`` as 0/1/2, or None."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            "Read",
            GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            1500,
            None,
        )
        value = result.unpack()[0]
        while isinstance(value, (tuple, list)):
            value = value[0]
        return int(value)
    except Exception:
        return None


def color_scheme_is_dark() -> bool:
    gtk_prefer = False
    settings = Gtk.Settings.get_default()
    if settings is not None:
        gtk_prefer = bool(settings.get_property("gtk-application-prefer-dark-theme"))
    return scheme_is_dark(
        portal=read_portal_color_scheme(),
        gnome=read_gnome_color_scheme(),
        gtk_prefer_dark=gtk_prefer,
    )


def sync_gtk_appearance() -> bool:
    """Push desktop color-scheme into this process. Returns True if dark."""
    dark = color_scheme_is_dark()
    settings = Gtk.Settings.get_default()
    if settings is None:
        return dark
    desktop_theme = read_gnome_gtk_theme()
    current = desktop_theme or settings.get_property("gtk-theme-name")
    settings.set_property("gtk-theme-name", adwaita_theme_for_scheme(current, dark))
    settings.set_property("gtk-application-prefer-dark-theme", dark)
    return dark


def watch_appearance(callback) -> None:
    """Reload chrome when Omarchy / GNOME / the portal flips color-scheme."""

    def _run(*_a):
        callback()

    try:
        iface = Gio.Settings.new("org.gnome.desktop.interface")
        iface.connect("changed::color-scheme", _run)
        iface.connect("changed::gtk-theme", _run)
        _WATCH_KEEPALIVE.append(iface)
    except Exception:
        pass
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            None,
        )

        def _on_signal(_proxy, _sender, signal, params):
            if signal not in ("SettingChanged", "SettingsChanged"):
                return
            unpacked = params.unpack()
            namespace = unpacked[0] if unpacked else ""
            key = unpacked[1] if len(unpacked) > 1 else ""
            if namespace == "org.freedesktop.appearance" and key == "color-scheme":
                _run()

        proxy.connect("g-signal", _on_signal)
        _WATCH_KEEPALIVE.append(proxy)
    except Exception:
        pass
