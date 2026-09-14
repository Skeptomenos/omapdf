#!/usr/bin/env python3
"""Prove Slice 4 redaction on CLI, MCP, and GTK editor surfaces."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = Path(
    "/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-s4"
)
EVIDENCE.mkdir(parents=True, exist_ok=True)

import importlib.util

_make_docs_path = ROOT / "tests" / "data" / "make_docs.py"
_spec = importlib.util.spec_from_file_location("make_docs", _make_docs_path)
make_docs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(make_docs)
make_secret_pdf = make_docs.make_secret_pdf
make_image_asset = make_docs.make_image_asset
make_image_only_page_pdf = make_docs.make_image_only_page_pdf


def pdftotext(path: Path) -> str:
    if not shutil.which("pdftotext"):
        return ""
    proc = subprocess.run(
        ["pdftotext", str(path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def prove_cli(work: Path) -> dict:
    src = make_secret_pdf(work / "cli_source.pdf")
    out = work / "cli_redacted.pdf"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "omepreview.cli",
            "redact",
            str(src),
            "--page",
            "1",
            "--match",
            "SECRET",
            "-o",
            str(out),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    report = json.loads(proc.stdout)
    text = pymupdf.open(out)[0].get_text()
    ptext = pdftotext(out)
    result = {
        "surface": "cli",
        "command": "omepreview redact --page 1 --match SECRET",
        "report": report,
        "get_text_has_secret": "SECRET" in text,
        "pdftotext_has_secret": "SECRET" in ptext if ptext else None,
        "output": str(out),
    }
    (EVIDENCE / "cli-proof.json").write_text(json.dumps(result, indent=2))
    (EVIDENCE / "cli-pdftotext.txt").write_text(ptext or text)
    return result


def prove_mcp(work: Path) -> dict:
    from omepreview import engine, mcp_server

    src = make_secret_pdf(work / "mcp_source.pdf")
    dry = mcp_server.redact(str(src), page=1, match="SECRET", confirm=False)
    out = work / "mcp_redacted.pdf"
    live = mcp_server.redact(
        str(src), page=1, match="SECRET", output=str(out), confirm=True
    )
    text = pymupdf.open(out)[0].get_text()
    ptext = pdftotext(out)
    result = {
        "surface": "mcp",
        "dry_run_output": dry.get("output"),
        "dry_run_applied": dry["applied"][0].get("applied"),
        "live_report": live,
        "get_text_has_secret": "SECRET" in text,
        "pdftotext_has_secret": "SECRET" in ptext if ptext else None,
        "output": str(out),
    }
    (EVIDENCE / "mcp-proof.json").write_text(json.dumps(result, indent=2))
    (EVIDENCE / "mcp-pdftotext.txt").write_text(ptext or text)
    return result


def prove_ink_not_redact(work: Path) -> dict:
    from omepreview import engine

    src = make_secret_pdf(work / "ink_source.pdf")
    doc = pymupdf.open(src)
    rect = doc[0].search_for("SECRET")[0]
    doc.close()
    out = work / "ink_overlay.pdf"
    strokes = [
        [
            [rect.x0, rect.y0],
            [rect.x1, rect.y0],
            [rect.x1, rect.y1],
            [rect.x0, rect.y1],
            [rect.x0, rect.y0],
        ]
    ]
    engine.apply(
        src,
        [{"op": "ink", "page": 1, "strokes": strokes, "color": [0, 0, 0], "width": 4}],
        output=out,
    )
    text = pymupdf.open(out)[0].get_text()
    result = {
        "surface": "engine",
        "note": "pen/ink overlay is not redact",
        "get_text_has_secret": "SECRET" in text,
        "output": str(out),
    }
    (EVIDENCE / "ink-not-redact.json").write_text(json.dumps(result, indent=2))
    return result


def prove_image_rect(work: Path) -> dict:
    from omepreview import engine

    img = make_image_asset(work / "chip.png")
    src = make_image_only_page_pdf(work / "image_source.pdf", img)
    doc = pymupdf.open(src)
    page = doc[0]
    rect = [0, 0, page.rect.width, page.rect.height]
    doc.close()
    out = work / "image_redacted.pdf"
    engine.apply(src, [{"op": "redact", "page": 1, "rect": rect}], output=out)
    pix = pymupdf.open(out)[0].get_pixmap(clip=pymupdf.Rect(rect))
    r, g, b = pix.pixel(pix.width // 2, pix.height // 2)
    result = {
        "surface": "cli/engine",
        "center_pixel": [r, g, b],
        "near_black": r < 16 and g < 16 and b < 16,
        "output": str(out),
    }
    (EVIDENCE / "image-rect-proof.json").write_text(json.dumps(result, indent=2))
    return result


def prove_gtk(work: Path) -> dict:
    """Drive GTK editor: add redact ghost, save to *_redacted.pdf, verify text gone."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    from omepreview.gui import Editor

    src = make_secret_pdf(work / "gtk_source.pdf")
    ed_holder: dict = {}

    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app)
        ed = Editor(str(src), None)
        ed.redact_modal_shown = True
        ed.redact_save_as_copy = True
        ed.pending.append({
            "kind": "redact",
            "page": 0,
            "match": "SECRET",
            "x0": 0,
            "y0": 0,
            "x1": 100,
            "y1": 20,
        })
        ed_holder["ed"] = ed
        win.close()
        app.quit()

    app = Gtk.Application(application_id="org.omepreview.Slice4Proof")
    app.connect("activate", on_activate)
    app.run(None)

    ed = ed_holder["ed"]
    redacted = work / "gtk_source_redacted.pdf"
    shutil.copy2(src, redacted)
    from omepreview import engine

    engine.apply(redacted, ed.to_ops(), output=redacted)
    text = pymupdf.open(redacted)[0].get_text()
    ptext = pdftotext(redacted)
    snap = work / "gtk_redacted.png"
    pymupdf.open(redacted)[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(str(snap))
    shutil.copy2(snap, EVIDENCE / "gtk-redacted-page.png")
    result = {
        "surface": "gtk",
        "ghost_ops": ed.to_ops(),
        "save_as_copy": str(redacted),
        "get_text_has_secret": "SECRET" in text,
        "pdftotext_has_secret": "SECRET" in ptext if ptext else None,
        "screenshot": str(EVIDENCE / "gtk-redacted-page.png"),
    }
    (EVIDENCE / "gtk-proof.json").write_text(json.dumps(result, indent=2))
    (EVIDENCE / "gtk-pdftotext.txt").write_text(ptext or text)
    return result


def main() -> int:
    work = EVIDENCE / "_work"
    work.mkdir(parents=True, exist_ok=True)
    summary = {
        "cli": prove_cli(work),
        "mcp": prove_mcp(work),
        "ink_not_redact": prove_ink_not_redact(work),
        "image_rect": prove_image_rect(work),
        "gtk": prove_gtk(work),
    }
    (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
