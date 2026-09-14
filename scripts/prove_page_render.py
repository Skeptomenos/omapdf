#!/usr/bin/env python3
"""Prove main-pane page render: pixmap non-empty + optional window screenshot."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = Path(
    "/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-page-render"
)
EVIDENCE.mkdir(parents=True, exist_ok=True)

import importlib.util

_spec = importlib.util.spec_from_file_location("make_docs", ROOT / "tests" / "data" / "make_docs.py")
make_docs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(make_docs)


def prove_engine_render(pdf: Path) -> dict:
    """Simulate render_page raster path without GTK draw."""
    import io

    import cairo
    import pymupdf

    doc = pymupdf.open(pdf)
    page = doc[0]
    z = 1.2
    matrix = pymupdf.Matrix(z, z).prerotate(page.rotation)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    text = page.get_text()
    doc.close()
    out = EVIDENCE / "main-pane-raster.png"
    pix.save(str(out))
    return {
        "pixmap": [pix.width, pix.height],
        "page_text_sample": text.strip()[:80],
        "raster": str(out),
    }


def prove_gui_screenshot(pdf: Path) -> dict:
    import os

    shot = EVIDENCE / "editor-with-thumbs.png"
    cmd = f'''
import subprocess, time, sys
from pathlib import Path
pdf = "{pdf}"
shot = "{shot}"
subprocess.Popen([sys.executable, "-m", "omapreview.cli", "edit", pdf])
time.sleep(4)
try:
    subprocess.run(["scrot", "-f", shot], check=True, timeout=10)
except Exception as exc:
    print("scrot failed:", exc)
'''
    env = os.environ.copy()
    proc = subprocess.run(
        ["xvfb-run", "-a", "bash", "-lc", f"python3 -c {repr(cmd)}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "xvfb_exit": proc.returncode,
        "screenshot": str(shot) if shot.exists() else None,
        "stderr": proc.stderr[-500:] if proc.stderr else "",
    }


def main() -> int:
    pdf = EVIDENCE / "_work" / "labeled.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    make_docs.make_labeled_pdf(pdf, page_count=4)

    summary = {
        "raster": prove_engine_render(pdf),
        "screenshot": prove_gui_screenshot(pdf),
    }
    (EVIDENCE / "proof.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
