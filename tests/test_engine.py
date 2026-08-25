"""End-to-end tests over a generated sample document."""

import json
import subprocess
import sys

import pymupdf
import pytest

from omapdf import engine, read, signature
from omapdf.ops import OpError


@pytest.fixture()
def sample_pdf(tmp_path):
    """Two-page PDF: page 1 has prose, page 2 has a form + signature line."""
    doc = pymupdf.open()
    page = doc.new_page()  # 612x792 letter
    page.insert_text((72, 100), "RENTAL AGREEMENT", fontsize=16)
    page.insert_text((72, 140), "The tenant agrees to the early termination clause.", fontsize=11)
    page.insert_text((72, 160), "Rent is due on the first of each month.", fontsize=11)

    page2 = doc.new_page()
    page2.insert_text((72, 100), "Tenant name:", fontsize=11)
    widget = pymupdf.Widget()
    widget.field_name = "tenant_name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(160, 88, 400, 106)
    page2.add_widget(widget)
    page2.insert_text((72, 300), "Signature:", fontsize=11)

    path = tmp_path / "lease.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def sig_home(tmp_path, monkeypatch):
    """Isolate the signature store and save a tiny 'signature'."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 40), True)
    png = tmp_path / "sig.png"
    pix.save(str(png))
    signature.add(png, "default")
    return png


def test_read_extracts_text_and_fields(sample_pdf):
    data = read.extract(sample_pdf)
    assert data["page_count"] == 2
    assert data["has_form"]
    page1 = data["pages"][0]
    assert any("termination" in b["text"] for b in page1["text_blocks"])
    fields = data["pages"][1]["form_fields"]
    assert fields[0]["name"] == "tenant_name"


def test_highlight_by_match(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = engine.apply(
        sample_pdf,
        [{"op": "highlight", "page": 1, "match": "early termination clause"}],
        output=out,
    )
    assert result["applied"][0]["rects"]
    annots = read.extract(out)["pages"][0]["annotations"]
    assert annots and annots[0]["type"] == "Highlight"


def test_highlight_missing_text_fails_actionably(sample_pdf):
    with pytest.raises(OpError, match="omapdf read"):
        engine.apply(sample_pdf, [{"op": "highlight", "page": 1, "match": "no such words"}])


def test_fill_field_and_flatten(sample_pdf, tmp_path):
    out = tmp_path / "filled.pdf"
    engine.apply(
        sample_pdf,
        [{"op": "fill_field", "field": "tenant_name", "value": "Peter Bergin"}],
        output=out,
    )
    fields = read.form_fields(out)
    assert fields[0]["value"] == "Peter Bergin"

    flat = tmp_path / "flat.pdf"
    engine.flatten(out, output=flat)
    data = read.extract(flat)
    assert not data["has_form"]
    assert any(
        "Peter Bergin" in b["text"] for b in data["pages"][1]["text_blocks"]
    )


def test_fill_unknown_field_lists_real_ones(sample_pdf):
    with pytest.raises(OpError, match="tenant_name"):
        engine.apply(sample_pdf, [{"op": "fill_field", "field": "nope", "value": "x"}])


def test_place_signature_with_date(sample_pdf, sig_home, tmp_path):
    out = tmp_path / "signed.pdf"
    result = engine.apply(
        sample_pdf,
        [{"op": "place_signature", "page": 2, "at": [140, 290], "width": 150, "date": True}],
        output=out,
    )
    placement = result["applied"][0]
    assert placement["rect"][2] - placement["rect"][0] == pytest.approx(150)
    assert "date" in placement
    assert out.is_file()


def test_dry_run_writes_nothing(sample_pdf, sig_home):
    before = sample_pdf.read_bytes()
    result = engine.apply(
        sample_pdf,
        [{"op": "place_signature", "page": 2, "at": [140, 290]}],
        dry_run=True,
    )
    assert result["output"] is None
    assert result["applied"][0]["applied"] is False
    assert sample_pdf.read_bytes() == before


def test_cli_end_to_end(sample_pdf, sig_home, tmp_path):
    out = tmp_path / "cli.pdf"
    run = subprocess.run(
        [
            sys.executable, "-m", "omapdf.cli", "annotate", str(sample_pdf),
            "--page", "1", "--match", "Rent is due", "--style", "underline",
            "-o", str(out), "--json",
        ],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["applied"][0]["style"] == "underline"
