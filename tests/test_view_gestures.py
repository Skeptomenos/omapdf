"""Live pinch math and signature drag payload — no GTK, no raster."""

from pathlib import Path

from omepreview.view_gestures import (
    SIG_DND_PREFIX,
    clamp_zoom_pct,
    current_zoom_pct,
    parse_signature_dnd,
    pinch_live_pct,
    pinch_pixmap_scale,
    signature_dnd_payload,
    signature_ghost,
)


def test_pinch_live_pct_clamps():
    assert pinch_live_pct(100.0, 1.0) == 100.0
    assert pinch_live_pct(100.0, 2.0) == 200.0
    assert pinch_live_pct(100.0, 8.0) == 400.0
    assert pinch_live_pct(100.0, 0.1) == 25.0


def test_pinch_pixmap_scale_is_relative_to_committed_raster():
    assert pinch_pixmap_scale(100.0, 150.0) == 1.5
    assert pinch_pixmap_scale(80.0, 80.0) == 1.0
    assert pinch_pixmap_scale(0.0, 100.0) == 1.0


def test_fit_page_zoom_pct_from_scale():
    # matrix zoom 1.0 ↔ 75% (100% is 96/72 CSS-px per PDF point)
    assert current_zoom_pct(None, 1.0) == 75.0
    assert current_zoom_pct(None, 96 / 72) == 100.0
    assert current_zoom_pct(200.0, 1.0) == 200.0


def test_clamp_zoom_pct():
    assert clamp_zoom_pct(10) == 25.0
    assert clamp_zoom_pct(999) == 400.0


def test_signature_dnd_roundtrip():
    payload = signature_dnd_payload("default")
    assert payload == f"{SIG_DND_PREFIX}default"
    assert parse_signature_dnd(payload) == "default"
    assert parse_signature_dnd("nope") is None
    assert parse_signature_dnd("") is None
    assert parse_signature_dnd(None) is None


def test_signature_dnd_from_store_path(tmp_path):
    svg = tmp_path / "Downloads" / "omapreview" / "signature" / "initials.svg"
    svg.parent.mkdir(parents=True)
    svg.write_text("<svg/>")
    assert parse_signature_dnd(str(svg)) == "initials"
    assert parse_signature_dnd(svg.as_uri()) == "initials"
    stray = tmp_path / "other.svg"
    stray.write_text("<svg/>")
    assert parse_signature_dnd(str(stray)) is None


def test_signature_ghost_centers_on_drop_point():
    g = signature_ghost(2, "default", 200.0, 100.0, aspect=0.5, width=160.0)
    assert g["kind"] == "sig"
    assert g["page"] == 2
    assert g["signature"] == "default"
    assert g["x"] == 120.0
    assert g["y"] == 60.0
    assert g["w"] == 160.0
    assert g["h"] == 80.0
    assert g["date"] is False


class _FakeFile:
    def __init__(self, path: Path):
        self._path = str(path)

    def get_path(self):
        return self._path


def test_signature_dnd_from_gio_file_like(tmp_path):
    svg = tmp_path / "signature" / "jane.svg"
    svg.parent.mkdir()
    svg.write_text("<svg/>")
    assert parse_signature_dnd(_FakeFile(svg)) == "jane"


def test_pinch_scale_changed_does_not_rerasterize_pdf():
    """ANR guard: scale-changed must transform the pixmap, not call render_page."""
    src = Path(__file__).resolve().parents[1] / "src" / "omepreview" / "gui.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def on_pinch(_gesture, scale):")
    end = text.index("def commit_pinch_zoom():")
    body = text[start:end]
    assert "render_page()" not in body
    assert "queue_draw()" in body
    assert "pinch_pixmap_scale" in body
