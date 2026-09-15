"""Launcher name, console-script alias, and desktop entry."""

from pathlib import Path

import tomllib

from omepreview.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_omapreview_console_script_alias():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert data["project"]["version"] == "0.1.0"
    assert scripts["omapreview"] == "omepreview.cli:main"
    assert scripts["omepreview"] == "omepreview.cli:main"
    assert data["project"]["urls"]["Homepage"] == "https://github.com/Skeptomenos/omapreview"


def test_omapreview_desktop_is_the_launcher_entry():
    text = (ROOT / "share/omapreview.desktop").read_text(encoding="utf-8")
    assert "Name=omapreview\n" in text
    assert "Exec=omapreview edit %f" in text
    assert "TryExec=omapreview" in text
    assert "NoDisplay=true" not in text
    assert "MimeType=application/pdf;" in text


def test_legacy_omepreview_desktop_is_hidden():
    text = (ROOT / "share/omepreview.desktop").read_text(encoding="utf-8")
    assert "NoDisplay=true" in text
    assert "Exec=omapreview edit %f" in text


def test_pkgbuild_installs_omapreview_desktop_from_omapreview_repo():
    text = (ROOT / "packaging/PKGBUILD").read_text(encoding="utf-8")
    assert "pkgname=omapreview" in text
    assert "pkgver=0.1.0" in text
    assert "share/omapreview.desktop" in text
    assert "$pkgdir/usr/share/applications/omapreview.desktop" in text
    assert 'url="https://github.com/Skeptomenos/omapreview"' in text
    assert "archive/refs/tags/v$pkgver.tar.gz" in text
    assert "python-pymupdf" in text
    assert "python-gobject" in text
    assert "python-cairo" in text
    assert "gtk4" in text
    assert "git+$url" not in text
    assert "sha256sums=('SKIP')" not in text
    assert "67e1aa28845b4b4e016a2d6b38a065d9c501abef53f482330c819ef0068fb8bc" in text
    assert 'cd "$pkgname-$pkgver"' in text


def test_edit_accepts_a_missing_pdf_for_the_launcher():
    args = build_parser().parse_args(["edit"])
    assert args.pdf is None
    args = build_parser().parse_args(["edit", "doc.pdf"])
    assert args.pdf == "doc.pdf"
