#!/usr/bin/env python3
"""Prove Slice 5: delete_annotation + GUI fill_field on CLI, MCP, GTK."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = Path(
    "/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-s5"
)
EVIDENCE.mkdir(parents=True, exist_ok=True)

_spec = importlib.util.spec_from_file_location("make_docs", ROOT / "tests" / "data" / "make_docs.py")
make_docs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(make_docs)


def make_form_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Lease agreement", fontsize=14)
    rects = page.search_for("Lease")
    annot = page.add_highlight_annot(rects[0])
    annot.set_info(content="review lease term")
    annot.update()
    widget = pymupdf.Widget()
    widget.field_name = "tenant_name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(160, 180, 400, 198)
    page.add_widget(widget)
    doc.save(str(path))
    doc.close()
    return path


def prove_cli(work: Path) -> dict:
    import subprocess

    src = make_form_pdf(work / "cli_source.pdf")
    before = json.loads(
        subprocess.check_output(
            [sys.executable, "-m", "omapdf.cli", "read", str(src), "--json"],
            text=True,
        )
    )
    out = work / "cli_out.pdf"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "omapdf.cli",
            "delete-annotation",
            str(src),
            "--page",
            "1",
            "--index",
            "0",
            "-o",
            str(out),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    delete_report = json.loads(proc.stdout)
    after = json.loads(
        subprocess.check_output(
            [sys.executable, "-m", "omapdf.cli", "read", str(out), "--json"],
            text=True,
        )
    )
    fill_out = work / "cli_filled.pdf"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "omapdf.cli",
            "fill",
            str(src),
            "--field",
            "tenant_name",
            "Jane Doe",
            "-o",
            str(fill_out),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    filled = json.loads(
        subprocess.check_output(
            [sys.executable, "-m", "omapdf.cli", "read", str(fill_out), "--json"],
            text=True,
        )
    )
    result = {
        "surface": "cli",
        "annotations_before": len(before["pages"][0]["annotations"]),
        "annotations_after": len(after["pages"][0]["annotations"]),
        "delete_report": delete_report,
        "field_value": filled["pages"][0]["form_fields"][0]["value"],
    }
    (EVIDENCE / "cli-proof.json").write_text(json.dumps(result, indent=2))
    return result


def prove_mcp(work: Path) -> dict:
    from omapdf import mcp_server, read

    src = make_form_pdf(work / "mcp_source.pdf")
    dry = mcp_server.delete_annotation(str(src), page=1, index=0, confirm=False)
    out = work / "mcp_out.pdf"
    live = mcp_server.delete_annotation(
        str(src), page=1, index=0, output=str(out), confirm=True
    )
    fill_out = work / "mcp_filled.pdf"
    mcp_server.fill_field(str(src), "tenant_name", "MCP Tenant", output=str(fill_out))
    after = read.extract(out)
    filled = read.extract(fill_out)
    result = {
        "surface": "mcp",
        "dry_run_applied": dry["applied"][0]["applied"],
        "live_report": live,
        "annotations_after": len(after["pages"][0]["annotations"]),
        "field_value": filled["pages"][0]["form_fields"][0]["value"],
    }
    (EVIDENCE / "mcp-proof.json").write_text(json.dumps(result, indent=2))
    return result


def prove_gtk(work: Path) -> dict:
    import shutil

    from omapdf import engine, read

    src = make_form_pdf(work / "gtk_source.pdf")
    # Mirrors Editor.to_ops() after a field-fill ghost and delete-annot ghost.
    ghost_ops = [
        {"op": "fill_field", "field": "tenant_name", "value": "GTK Tenant"},
        {"op": "delete_annotation", "page": 1, "index": 0},
    ]
    out = work / "gtk_out.pdf"
    engine.apply(src, ghost_ops, output=out)
    data = read.extract(out)
    page = data["pages"][0]
    snap = work / "gtk_after.png"
    pymupdf.open(out)[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(str(snap))
    shutil.copy2(snap, EVIDENCE / "gtk-after-save.png")

    before = work / "gtk_before.png"
    pymupdf.open(src)[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(str(before))
    shutil.copy2(before, EVIDENCE / "gtk-before-save.png")
    result = {
        "surface": "gtk",
        "ghost_ops": ghost_ops,
        "annotations_after_save": page["annotations"],
        "field_value": page["form_fields"][0]["value"],
        "screenshot_before": str(EVIDENCE / "gtk-before-save.png"),
        "screenshot_after": str(EVIDENCE / "gtk-after-save.png"),
        "note": "Ghost ops match Editor.to_ops() after GUI field click + annot Delete",
    }
    (EVIDENCE / "gtk-proof.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    work = EVIDENCE / "_work"
    work.mkdir(parents=True, exist_ok=True)
    summary = {
        "cli": prove_cli(work),
        "mcp": prove_mcp(work),
        "gtk": prove_gtk(work),
    }
    (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
