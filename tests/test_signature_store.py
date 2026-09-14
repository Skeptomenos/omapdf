"""Signature store: SVG is the recorded format; PNG import still works."""

from pathlib import Path

import pymupdf

from omepreview import signature
from omepreview.draw import render_pad_png
from omepreview.trackpad_sig import RecorderSession


def test_add_and_list_svg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    svg = tmp_path / "jane.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="30">'
        '<path d="M 2 20 L 70 8" fill="none" stroke="#000" stroke-width="3"/>'
        "</svg>",
        encoding="utf-8",
    )
    dest = signature.add(svg, "jane")
    assert dest.suffix == ".svg"
    assert dest.parent.name == "signatures"
    assert dest.parent.parent.name == "omepreview"
    assert signature.list_names() == ["jane"]
    assert signature.get("jane") == dest


def test_png_import_still_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 16), True)
    png = tmp_path / "old.png"
    pix.save(str(png))
    dest = signature.add(png, "legacy")
    assert dest.suffix == ".png"
    assert signature.get("legacy") == dest


def test_render_pad_png_is_png(tmp_path):
    session = RecorderSession(pad_size=(516.0, 336.0))
    session.handle_space()
    for x in range(20, 180, 4):
        session.add_point(x, 80 + 18 * ((x // 8) % 3 - 1), button1=False)
    path = tmp_path / "pad.png"
    render_pad_png(path, session)
    assert path.is_file()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
