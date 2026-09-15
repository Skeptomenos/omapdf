"""Desktop entry and PKGBUILD stay a PATH-launched Omarchy app."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_exec_is_path_binary_not_venv():
    text = (ROOT / "share/omepreview.desktop").read_text(encoding="utf-8")
    assert "Exec=omepreview open %f" in text
    assert "TryExec=omepreview" in text
    assert "MimeType=application/pdf;" in text
    assert "Name=omepreview" in text
    assert "Icon=omepreview" in text
    assert ".venv" not in text
    assert "StartupWMClass=org.omepreview.Editor" in text


def test_packaged_icon_exists():
    svg = ROOT / "share/icons/hicolor/scalable/apps/omepreview.svg"
    assert svg.is_file()
    blob = svg.read_text(encoding="utf-8")
    assert "<svg" in blob


def test_pkgbuild_uses_github_omapreview_and_local_tree():
    text = (ROOT / "packaging/PKGBUILD").read_text(encoding="utf-8")
    assert 'url="https://github.com/Skeptomenos/omapreview"' in text
    assert "pkgname=omepreview" in text
    assert "share/omepreview.desktop" in text
    assert "omepreview.svg" in text
    assert "source=()" in text
    assert "github.com/Skeptomenos/omepreview.git" not in text


def test_open_and_edit_accept_missing_pdf():
    from omepreview.cli import build_parser

    opened = build_parser().parse_args(["open"])
    assert opened.pdf is None
    edited = build_parser().parse_args(["edit"])
    assert edited.pdf is None
    with_file = build_parser().parse_args(["open", "/tmp/doc.pdf"])
    assert with_file.pdf == "/tmp/doc.pdf"


def test_pdf_or_pick_returns_given_path():
    from argparse import Namespace

    from omepreview.cli import _pdf_or_pick

    assert _pdf_or_pick(Namespace(pdf="/tmp/doc.pdf")) == "/tmp/doc.pdf"
