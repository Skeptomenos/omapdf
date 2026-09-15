"""Omarchy ``colors.toml`` palette: locate, parse, derive, emit GTK CSS.

Canonical path is ``~/.local/state/omarchy/current/theme/colors.toml``
(legacy: ``~/.config/omarchy/current/theme/colors.toml``). ``omarchy-theme-set``
renders the next theme into a sibling directory and swaps ``theme/`` in
atomically, then fires the ``theme-set`` hook. Consumers watch the parent
``current/`` directory so the swap is visible; missing or invalid palettes
fall back off Omarchy (Adwaita color-scheme).

Derivation matches ``omarchy-theme-color`` (semantic keys, legacy short
names, ANSI ``color0``–``color15``, mixed shades). This app additionally
requires ``background``, ``foreground``, ``accent``, ``red``, ``yellow``,
and ``green`` to resolve to ``#rrggbb`` before the palette is applied.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REQUIRED_KEYS = ("background", "foreground", "accent", "red", "yellow", "green")

_HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")
_HEX3 = re.compile(r"^#[0-9A-Fa-f]{3}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

_LEGACY_SHORT = {
    "background": "bg",
    "dark_background": "dark_bg",
    "darker_background": "darker_bg",
    "lighter_background": "lighter_bg",
    "foreground": "fg",
    "dark_foreground": "dark_fg",
    "light_foreground": "light_fg",
    "bright_foreground": "bright_fg",
}

_ANSI_TO_SEMANTIC = {
    "red": "color1",
    "green": "color2",
    "yellow": "color3",
    "blue": "color4",
    "magenta": "color5",
    "cyan": "color6",
    "bright_red": "color9",
    "bright_green": "color10",
    "bright_yellow": "color11",
    "bright_blue": "color12",
    "bright_magenta": "color13",
    "bright_cyan": "color14",
}

_SEMANTIC_TO_ANSI = {
    "color0": "background",
    "color1": "red",
    "color2": "green",
    "color3": "yellow",
    "color4": "blue",
    "color5": "magenta",
    "color6": "cyan",
    "color7": "foreground",
    "color8": "muted",
    "color9": "bright_red",
    "color10": "bright_green",
    "color11": "bright_yellow",
    "color12": "bright_blue",
    "color13": "bright_magenta",
    "color14": "bright_cyan",
    "color15": "bright_foreground",
}

_GTK_THEME_COLORS = (
    ("theme_bg_color", "background"),
    ("theme_fg_color", "foreground"),
    ("theme_selected_bg_color", "accent"),
    ("theme_selected_fg_color", "bright_foreground"),
    ("theme_unfocused_bg_color", "dark_background"),
    ("theme_unfocused_fg_color", "muted"),
    ("accent_color", "accent"),
    ("accent_bg_color", "accent"),
    ("destructive_color", "red"),
    ("warning_color", "yellow"),
    ("success_color", "green"),
)

_LINE = re.compile(
    r'^\s*(?:export\s+)?([A-Za-z0-9_-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^#\n]+?))'
    r"\s*(?:#.*)?$"
)


def normalize_hex(value: str) -> str | None:
    """Return ``#rrggbb`` or None."""
    raw = (value or "").strip()
    if _HEX6.match(raw):
        return "#" + raw[1:].lower()
    if _HEX3.match(raw):
        r, g, b = raw[1], raw[2], raw[3]
        return f"#{r}{r}{g}{g}{b}{b}".lower()
    return None


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    hex6 = normalize_hex(value)
    if hex6 is None:
        raise ValueError(f"not a #rrggbb color: {value!r}")
    h = hex6[1:]
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def mix_hex(start: str, end: str, amount: float) -> str:
    """Mix ``start`` toward ``end``. ``amount`` is 0..1 (``0.25`` or ``25%``)."""
    if amount > 1:
        amount = amount / 100.0
    amount = min(1.0, max(0.0, amount))
    s = normalize_hex(start)
    e = normalize_hex(end)
    if s is None or e is None:
        raise ValueError("mix_hex needs #rrggbb colors")
    sr, sg, sb = (int(s[i : i + 2], 16) for i in (1, 3, 5))
    er, eg, eb = (int(e[i : i + 2], 16) for i in (1, 3, 5))
    red = int(sr * (1 - amount) + er * amount + 0.5)
    green = int(sg * (1 - amount) + eg * amount + 0.5)
    blue = int(sb * (1 - amount) + eb * amount + 0.5)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _env_map(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def colors_toml_candidates(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    """Canonical state path first, then the legacy config symlink path."""
    env = _env_map(env)
    override = (env.get("OMEPREVIEW_OMARCHY_COLORS") or "").strip()
    if override:
        return [Path(override).expanduser()]
    home = Path(home) if home is not None else Path.home()
    state = Path(env.get("XDG_STATE_HOME") or (home / ".local" / "state"))
    config = Path(env.get("XDG_CONFIG_HOME") or (home / ".config"))
    paths = [
        state / "omarchy" / "current" / "theme" / "colors.toml",
        home / ".local" / "state" / "omarchy" / "current" / "theme" / "colors.toml",
        config / "omarchy" / "current" / "theme" / "colors.toml",
        home / ".config" / "omarchy" / "current" / "theme" / "colors.toml",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path if not path.exists() else path.resolve()
        key = resolved if path.exists() else path
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def locate_colors_toml(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    for path in colors_toml_candidates(home=home, env=env):
        if path.is_file():
            return path
    return None


def theme_watch_paths(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    """Directories whose change means ``omarchy-theme-set`` swapped the theme.

    ``omarchy-themes`` watches the parent of ``theme/`` so an atomic replace
    of that directory is visible. Same roots here; the ``theme-set`` hook
    runs after that swap.
    """
    roots: list[Path] = []
    seen: set[Path] = set()
    for colors in colors_toml_candidates(home=home, env=env):
        for path in (colors, colors.parent, colors.parent.parent):
            if path in seen:
                continue
            seen.add(path)
            roots.append(path)
    return roots


def parse_colors_toml(text: str) -> dict[str, str]:
    """Flat ``key = value`` map. Prefers TOML; falls back to the shell parser."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return _parse_colors_lines(text)
    out: dict[str, str] = {}
    if not isinstance(data, dict):
        return _parse_colors_lines(text)
    for key, value in data.items():
        if not _KEY.match(str(key)):
            continue
        if isinstance(value, str):
            out[str(key)] = value
    return out


def _parse_colors_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(raw)
        if not match:
            continue
        key, double, single, bare = match.groups()
        value = double if double is not None else single if single is not None else (bare or "")
        value = value.strip()
        if not _KEY.match(key):
            continue
        out[key] = value
    return out


def _alias(colors: dict[str, str], key: str, fallback: str) -> None:
    if key not in colors or colors[key] == "":
        other = colors.get(fallback)
        if other:
            colors[key] = other


def _fill_missing(colors: dict[str, str], key: str, value: str | None) -> None:
    if value and (key not in colors or colors[key] == ""):
        colors[key] = value


def resolve_theme_mode(colors: dict[str, str], *, colors_dir: Path | None = None) -> str:
    mode = (colors.get("mode") or colors.get("theme_type") or "").strip().lower()
    if mode in {"light", "dark"}:
        return mode
    if colors_dir is not None and (colors_dir / "light.mode").is_file():
        return "light"
    bg = normalize_hex(colors.get("background") or "")
    if bg:
        r, g, b = (int(bg[i : i + 2], 16) for i in (1, 3, 5))
        return "light" if (r + g + b) > 382 else "dark"
    return "dark"


def resolve_palette(
    raw: Mapping[str, str],
    *,
    colors_dir: Path | None = None,
) -> dict[str, str] | None:
    """Return the full derived palette, or None if a required color is missing."""
    colors = {str(k): str(v) for k, v in raw.items() if v is not None}
    for canonical, short in _LEGACY_SHORT.items():
        _alias(colors, canonical, short)

    _fill_missing(colors, "background", colors.get("color0"))
    _fill_missing(colors, "foreground", colors.get("color7"))
    if colors.get("background"):
        colors["color0"] = colors["background"]
    if colors.get("foreground"):
        colors["color7"] = colors["foreground"]

    for semantic, ansi in _ANSI_TO_SEMANTIC.items():
        _alias(colors, semantic, ansi)
    _alias(colors, "magenta", "purple")
    _alias(colors, "bright_magenta", "bright_purple")

    for key in REQUIRED_KEYS:
        hex6 = normalize_hex(colors.get(key) or "")
        if hex6 is None:
            return None
        colors[key] = hex6

    _fill_missing(colors, "blue", colors.get("color4") or colors.get("accent"))
    _fill_missing(
        colors,
        "magenta",
        colors.get("color5")
        or colors.get("purple")
        or mix_hex(colors["red"], colors["blue"], 0.5),
    )
    _fill_missing(
        colors,
        "cyan",
        colors.get("color6") or mix_hex(colors["green"], colors["blue"], 0.5),
    )

    _fill_missing(
        colors,
        "light_foreground",
        colors.get("color7") or colors.get("foreground"),
    )
    _fill_missing(
        colors,
        "bright_foreground",
        colors.get("color15") or colors.get("foreground"),
    )
    colors["cursor"] = colors["bright_foreground"]
    _fill_missing(
        colors,
        "lighter_background",
        colors.get("color0") or colors.get("background"),
    )
    _fill_missing(
        colors,
        "dark_foreground",
        colors.get("color8") or colors.get("foreground"),
    )
    _fill_missing(
        colors,
        "muted",
        colors.get("color8") or colors.get("dark_foreground"),
    )
    _fill_missing(
        colors,
        "selection",
        colors.get("selection_background")
        or colors.get("color8")
        or colors.get("color0")
        or colors.get("background"),
    )
    _fill_missing(colors, "selection_background", colors.get("selection"))
    _fill_missing(colors, "selection_foreground", colors.get("bright_foreground"))
    _fill_missing(colors, "orange", colors.get("yellow"))
    _fill_missing(colors, "brown", mix_hex(colors["orange"], "#000000", 0.5))

    _fill_missing(colors, "dark_background", mix_hex(colors["background"], "#000000", 0.25))
    _fill_missing(colors, "darker_background", mix_hex(colors["background"], "#000000", 0.5))
    for name in ("red", "yellow", "green", "cyan", "blue", "magenta"):
        _fill_missing(colors, f"bright_{name}", mix_hex(colors[name], "#ffffff", 0.2))
    _alias(colors, "purple", "magenta")
    _alias(colors, "bright_purple", "bright_magenta")

    for ansi, semantic in _SEMANTIC_TO_ANSI.items():
        _alias(colors, ansi, semantic)

    for canonical, short in _LEGACY_SHORT.items():
        if colors.get(canonical):
            colors[short] = colors[canonical]

    for key, value in list(colors.items()):
        hex6 = normalize_hex(value)
        if hex6 is not None:
            colors[key] = hex6

    mode = resolve_theme_mode(colors, colors_dir=colors_dir)
    colors["mode"] = mode
    colors["theme_type"] = mode
    return colors


@dataclass(frozen=True)
class Palette:
    colors: dict[str, str]
    path: Path | None = None

    @property
    def mode(self) -> str:
        return "light" if self.colors.get("mode") == "light" else "dark"

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"

    def get(self, key: str) -> str:
        return self.colors[key]

    def css_defines(self) -> bytes:
        """One CSS blob: GTK semantic tokens plus every hex palette key."""
        lines: list[str] = ["/* omarchy colors.toml — applied atomically */"]
        seen: set[str] = set()
        for gtk_name, key in _GTK_THEME_COLORS:
            value = self.colors.get(key)
            hex6 = normalize_hex(value or "")
            if hex6 is None:
                continue
            lines.append(f"@define-color {gtk_name} {hex6};")
            seen.add(gtk_name)
        for key in sorted(self.colors):
            hex6 = normalize_hex(self.colors[key])
            if hex6 is None:
                continue
            css_name = f"omarchy_{key}"
            if css_name in seen:
                continue
            lines.append(f"@define-color {css_name} {hex6};")
            seen.add(css_name)
        lines.append("")
        return "\n".join(lines).encode()


def load_palette(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> Palette | None:
    """Load and resolve the active Omarchy palette, or None to fall back."""
    colors_path = path if path is not None else locate_colors_toml(home=home, env=env)
    if colors_path is None or not colors_path.is_file():
        return None
    try:
        text = colors_path.read_text(encoding="utf-8")
    except OSError:
        return None
    raw = parse_colors_toml(text)
    resolved = resolve_palette(raw, colors_dir=colors_path.parent)
    if resolved is None:
        return None
    return Palette(colors=resolved, path=colors_path)
