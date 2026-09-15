"""Editor chrome: Omarchy ``colors.toml`` when present, else Adwaita.

On Omarchy, ``omarchy-theme-set`` writes
``~/.local/state/omarchy/current/theme/colors.toml`` (legacy:
``~/.config/omarchy/current/theme/colors.toml``) and fires the
``theme-set`` hook after an atomic swap of ``theme/``. This process reads
that palette at startup, applies every resolved color in one CSS load, and
watches ``current/`` so the swap (and therefore the hook) reloads chrome.

Off Omarchy, or when the file is missing/invalid, GNOME ``color-scheme`` plus
the freedesktop appearance portal drive Adwaita / Adwaita-dark. Prefer-dark
alone cannot lighten ``gtk-theme-name=Adwaita-dark``.

The PDF page is not themed: cairo still paints white paper. Hyprland owns
the window accent — chrome CSS does not draw a 2px frame.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from .palette import (
    REQUIRED_KEYS,
    Palette,
    colors_file_signature,
    hex_to_rgb,
    load_palette,
    locate_colors_toml,
    theme_watch_paths,
)

PORTAL_NO_PREFERENCE = 0
PORTAL_PREFER_DARK = 1
PORTAL_PREFER_LIGHT = 2

_WATCH_KEEPALIVE: list = []
_THEME_SET_DEBOUNCE_MS = 120

__all__ = [
    "PORTAL_NO_PREFERENCE",
    "PORTAL_PREFER_DARK",
    "PORTAL_PREFER_LIGHT",
    "Palette",
    "REQUIRED_KEYS",
    "adwaita_theme_for_scheme",
    "color_scheme_is_dark",
    "desk_is_light",
    "hex_to_rgb",
    "load_omarchy_palette",
    "locate_colors_toml",
    "scheme_is_dark",
    "sync_gtk_appearance",
    "watch_appearance",
    "watch_theme_set",
]


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
    """Pick the editorial desk shade from actual background luminance."""
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


def load_omarchy_palette() -> Palette | None:
    """Resolved Omarchy palette, or None to keep Adwaita."""
    try:
        return load_palette()
    except Exception:
        return None


def sync_gtk_appearance(*, dark: bool | None = None) -> bool:
    """Push color-scheme (or an Omarchy palette mode) into this process."""
    if dark is None:
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
    """Reload chrome when GNOME / the portal flips color-scheme."""

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


def watch_theme_set(callback) -> None:
    """Reload chrome when ``omarchy-theme-set`` swaps the theme (then the hook).

    Omarchy replaces ``theme/`` atomically, so monitors on the old
    ``colors.toml`` die after a swap. Re-arm on every wake, and poll the
    file signature so in-place edits are not missed.
    """

    pending = {"src": 0}
    seen: set[str] = set()
    last_sig = {"v": colors_file_signature(locate_colors_toml())}

    def fire():
        pending["src"] = 0
        _arm_theme_monitors(seen, on_changed)
        last_sig["v"] = colors_file_signature(locate_colors_toml())
        callback()
        return False

    def on_changed(*_a):
        src = pending["src"]
        if src:
            GLib.source_remove(src)
        pending["src"] = GLib.timeout_add(_THEME_SET_DEBOUNCE_MS, fire)

    def poll_signature():
        sig = colors_file_signature(locate_colors_toml())
        if sig != last_sig["v"]:
            on_changed()
        return True

    _arm_theme_monitors(seen, on_changed)
    GLib.timeout_add(400, poll_signature)
    _WATCH_KEEPALIVE.append(poll_signature)


def _arm_theme_monitors(seen: set[str], on_changed) -> None:
    try:
        flags = Gio.FileMonitorFlags.WATCH_MOVES
    except AttributeError:
        flags = Gio.FileMonitorFlags.NONE
    for path in theme_watch_paths():
        if not path.exists():
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            monitor = Gio.File.new_for_path(str(path)).monitor(flags, None)
            monitor.connect("changed", on_changed)
            _WATCH_KEEPALIVE.append(monitor)
        except Exception:
            continue
