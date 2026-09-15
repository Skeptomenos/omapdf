"""Omarchy colors.toml locate / parse / derive / CSS emit."""

from pathlib import Path

from omepreview.palette import (
    REQUIRED_KEYS,
    hex_to_rgb,
    load_palette,
    locate_colors_toml,
    mix_hex,
    parse_colors_toml,
    resolve_palette,
    theme_watch_paths,
)

DATA = Path(__file__).resolve().parent / "data"
TOKYO = DATA / "tokyo-night-colors.toml"

MINIMAL = """\
accent = "#7aa2f7"
background = "#1a1b26"
foreground = "#c0caf5"
red = "#f7768e"
yellow = "#e0af68"
green = "#9ece6a"
"""


def _write_theme(root: Path, text: str, *, state: bool = True) -> Path:
    base = (
        root / ".local" / "state" / "omarchy" / "current" / "theme"
        if state
        else root / ".config" / "omarchy" / "current" / "theme"
    )
    base.mkdir(parents=True)
    path = base / "colors.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_mix_hex_matches_omarchy_awk():
    assert mix_hex("#1a1b26", "#000000", 0.25) == "#14141d"
    assert mix_hex("#f7768e", "#ffffff", 0.2) == "#f991a5"


def test_tokyo_night_keeps_authored_keys():
    raw = parse_colors_toml(TOKYO.read_text(encoding="utf-8"))
    pal = resolve_palette(raw, colors_dir=TOKYO.parent)
    assert pal is not None
    assert pal["background"] == "#1a1b26"
    assert pal["foreground"] == "#a9b1d6"
    assert pal["accent"] == "#7aa2f7"
    assert pal["red"] == "#f7768e"
    assert pal["yellow"] == "#e0af68"
    assert pal["green"] == "#9ece6a"
    assert pal["muted"] == "#414868"
    assert pal["selection"] == "#292e42"
    assert pal["selection_background"] == "#292e42"
    assert pal["selection_foreground"] == "#c0caf5"
    assert pal["dark_background"] == "#13141c"
    assert pal["mode"] == "dark"
    assert pal["color1"] == pal["red"]
    assert pal["color2"] == pal["green"]
    assert pal["color3"] == pal["yellow"]
    assert pal["color4"] == pal["blue"]
    assert pal["color8"] == pal["muted"]
    assert pal["color15"] == pal["bright_foreground"]
    assert pal["urgent"] != pal["red"] if "urgent" in pal else True


def test_sparse_palette_derives_ramps_and_ansi():
    pal = resolve_palette(parse_colors_toml(MINIMAL))
    assert pal is not None
    for key in REQUIRED_KEYS:
        assert pal[key].startswith("#")
    assert pal["dark_background"] == mix_hex("#1a1b26", "#000000", 0.25)
    assert pal["darker_background"] == mix_hex("#1a1b26", "#000000", 0.5)
    assert pal["muted"] == pal["foreground"]
    assert pal["selection"] == pal["background"]
    assert pal["orange"] == pal["yellow"]
    assert pal["brown"] == mix_hex(pal["orange"], "#000000", 0.5)
    assert pal["blue"] == pal["accent"]
    assert pal["color0"] == pal["background"]
    assert pal["color7"] == pal["foreground"]
    assert pal["bright_red"] == mix_hex(pal["red"], "#ffffff", 0.2)
    assert pal["mode"] == "dark"


def test_legacy_short_names_and_ansi_satisfy_required():
    text = """\
bg = "#111111"
fg = "#eeeeee"
accent = "#2266ff"
color1 = "#cc3333"
color2 = "#33aa33"
color3 = "#dddd33"
"""
    pal = resolve_palette(parse_colors_toml(text))
    assert pal is not None
    assert pal["background"] == "#111111"
    assert pal["foreground"] == "#eeeeee"
    assert pal["red"] == "#cc3333"
    assert pal["green"] == "#33aa33"
    assert pal["yellow"] == "#dddd33"
    assert pal["bg"] == pal["background"]
    assert pal["fg"] == pal["foreground"]


def test_canonical_wins_over_legacy_alias():
    text = MINIMAL + 'bg = "#ffffff"\n'
    pal = resolve_palette(parse_colors_toml(text))
    assert pal is not None
    assert pal["background"] == "#1a1b26"


def test_missing_accent_is_invalid():
    text = """\
background = "#1a1b26"
foreground = "#c0caf5"
red = "#f7768e"
yellow = "#e0af68"
green = "#9ece6a"
"""
    assert resolve_palette(parse_colors_toml(text)) is None


def test_urgent_key_is_not_red():
    text = MINIMAL + 'urgent = "#ff00ff"\n'
    pal = resolve_palette(parse_colors_toml(text))
    assert pal is not None
    assert pal["red"] == "#f7768e"
    assert pal.get("urgent") == "#ff00ff"


def test_light_mode_file_and_luminance():
    pal = resolve_palette(
        parse_colors_toml(
            'accent="#2266ff"\nbackground="#f5f5f5"\nforeground="#222222"\n'
            'red="#cc0000"\nyellow="#ccaa00"\ngreen="#007700"\n'
        )
    )
    assert pal is not None
    assert pal["mode"] == "light"


def test_locate_canonical_beats_legacy(tmp_path):
    _write_theme(tmp_path, MINIMAL.replace("#7aa2f7", "#111111"), state=True)
    _write_theme(tmp_path, MINIMAL.replace("#7aa2f7", "#ffffff"), state=False)
    path = locate_colors_toml(home=tmp_path, env={})
    assert path is not None
    assert path.as_posix().endswith(".local/state/omarchy/current/theme/colors.toml")
    pal = load_palette(home=tmp_path, env={})
    assert pal is not None
    assert pal.get("accent") == "#111111"


def test_locate_legacy_when_canonical_missing(tmp_path):
    _write_theme(tmp_path, MINIMAL, state=False)
    path = locate_colors_toml(home=tmp_path, env={})
    assert path is not None
    assert ".config/omarchy/current/theme/colors.toml" in path.as_posix()


def test_no_omarchy_dir_returns_none(tmp_path):
    assert locate_colors_toml(home=tmp_path, env={}) is None
    assert load_palette(home=tmp_path, env={}) is None


def test_invalid_file_falls_back(tmp_path):
    _write_theme(tmp_path, "background = \"#1a1b26\"\n", state=True)
    assert load_palette(home=tmp_path, env={}) is None


def test_css_defines_full_palette_atomically():
    pal = load_palette(path=TOKYO)
    assert pal is not None
    blob = pal.css_defines().decode()
    assert blob.count("@define-color theme_bg_color") == 1
    assert "@define-color theme_bg_color #1a1b26;" in blob
    assert "@define-color theme_fg_color #a9b1d6;" in blob
    assert "@define-color theme_selected_bg_color #7aa2f7;" in blob
    assert "@define-color accent_color #7aa2f7;" in blob
    assert "@define-color destructive_color #f7768e;" in blob
    assert "@define-color warning_color #e0af68;" in blob
    assert "@define-color success_color #9ece6a;" in blob
    assert "@define-color omarchy_muted #414868;" in blob
    assert "border: 2px" not in blob
    rgb = hex_to_rgb(pal.get("background"))
    assert rgb[0] == 0x1A / 255.0


def test_theme_watch_paths_include_current_parent(tmp_path):
    _write_theme(tmp_path, MINIMAL, state=True)
    paths = theme_watch_paths(home=tmp_path, env={})
    joined = " ".join(p.as_posix() for p in paths)
    assert "omarchy/current" in joined
    assert "colors.toml" in joined
