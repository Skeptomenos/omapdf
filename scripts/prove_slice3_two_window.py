#!/usr/bin/env python3
"""Prove cross-window page clipboard: copy from A, paste into B, independent saves."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

import pymupdf

from omepreview import engine, pages as pages_mod
from omepreview.page_clipboard import (
    read_clipboard_pdf_bytes,
    push_clipboard,
    serialize_pages,
    write_temp_pdf,
)
from omepreview.page_preview import PagePreviewState
from tests.data.make_docs import make_labeled_pdf

EVIDENCE = Path(
    "/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-s3"
)


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    src_a = EVIDENCE / "window-a.pdf"
    src_b = EVIDENCE / "window-b.pdf"
    if not src_a.exists():
        make_labeled_pdf(src_a, 4, label_prefix="WINA")
    if not src_b.exists():
        make_labeled_pdf(src_b, 2, label_prefix="WINB")

    file_a = EVIDENCE / "prove-a.pdf"
    file_b = EVIDENCE / "prove-b.pdf"
    shutil.copy(src_a, file_a)
    shutil.copy(src_b, file_b)

    doc_a = pymupdf.open(str(file_a))
    json_bytes, pdf_bytes = serialize_pages(doc_a, [2, 3])
    doc_a.close()
    push_clipboard(json_bytes, pdf_bytes)

    got = read_clipboard_pdf_bytes()
    if not got:
        raise SystemExit("clipboard read failed")

    preview_b = PagePreviewState(file_b)
    tmp = write_temp_pdf(got)
    preview_b.add_insert_pdf(1, str(tmp), retain_source=True)

    for op in preview_b.page_ops:
        engine.apply(file_b, [op], output=file_b)
    preview_b.clear()

    listing_a = pages_mod.list_pages(file_a)
    listing_b = pages_mod.list_pages(file_b)
    (EVIDENCE / "prove-a-list.json").write_text(json.dumps(listing_a, indent=2))
    (EVIDENCE / "prove-b-list.json").write_text(json.dumps(listing_b, indent=2))

    doc_b = pymupdf.open(str(file_b))
    labels_b = [doc_b[i].get_text("text").strip() for i in range(doc_b.page_count)]
    doc_b.close()
    (EVIDENCE / "prove-page-labels.txt").write_text(
        f"window_a_pages={listing_a['page_count']}\n"
        f"window_b_pages={listing_b['page_count']}\n"
        f"window_b_labels={labels_b}\n"
    )

    result = {
        "window_a_pages": listing_a["page_count"],
        "window_b_pages": listing_b["page_count"],
        "independent": listing_a["page_count"] == 4 and listing_b["page_count"] == 4,
        "labels_b": labels_b,
    }
    (EVIDENCE / "two-window-proof.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["independent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
