#!/usr/bin/env python3
"""Apply the Slice 2 demo page-op sequence and verify save + list."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from omepreview import engine, pages as pages_mod
from omepreview.page_preview import PagePreviewState
from tests.data.make_docs import make_labeled_pdf

EVIDENCE = Path(
    "/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-s2"
)


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    demo = EVIDENCE / "demo-verify.pdf"
    insert_src = EVIDENCE / "insert-src.pdf"
    if not demo.exists():
        make_labeled_pdf(demo, 6)
    if not insert_src.exists():
        make_labeled_pdf(insert_src, 2, label_prefix="SRC")

    work = EVIDENCE / "demo-verify-working.pdf"
    shutil.copy(demo, work)

    state = PagePreviewState(work)
    state.add_delete_pages([2])
    state.add_rotate_pages([1], 90)
    state.add_move_pages([4, 5], after=1)
    state.add_insert_blank(state.page_count())
    state.add_insert_pdf(state.page_count() - 1, str(insert_src))

    for op in state.page_ops:
        engine.apply(work, [op], output=work)

    listing = pages_mod.list_pages(work)
    (EVIDENCE / "cli-list-after-save.json").write_text(json.dumps(listing, indent=2))

    import pymupdf

    doc = pymupdf.open(str(work))
    labels = [doc[i].get_text("text").strip() for i in range(doc.page_count)]
    doc.close()
    (EVIDENCE / "page-labels-after-save.txt").write_text(
        f"page_count {listing['page_count']}\nlabels {labels}\n"
    )
    print(json.dumps({"page_count": listing["page_count"], "labels": labels}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
