"""In-memory scratch preview for pending page operations (GUI + tests)."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pymupdf

from . import engine


class PagePreviewState:
    """Tracks page-op ghosts and a scratch PDF that reflects them."""

    def __init__(self, source: str | Path):
        self.source = str(Path(source).resolve())
        self.page_ops: list[dict] = []
        self.scratch_path: str | None = None
        self.inserted_pages: set[int] = set()  # 1-based pages in scratch view
        self._temp_sources: list[Path] = []

    def retarget(self, source: str | Path):
        """Point the preview at a different file (e.g. after save-as-copy)."""
        self.clear()
        self.source = str(Path(source).resolve())

    def has_changes(self) -> bool:
        return bool(self.page_ops)

    def clear(self):
        self.page_ops.clear()
        self._drop_scratch()
        self.inserted_pages.clear()
        self._drop_temp_sources()

    def _drop_scratch(self):
        if self.scratch_path and os.path.exists(self.scratch_path):
            os.unlink(self.scratch_path)
        self.scratch_path = None

    def _drop_temp_sources(self):
        for path in self._temp_sources:
            path.unlink(missing_ok=True)
        self._temp_sources.clear()

    def _remember_source(self, path: str | Path) -> str:
        p = Path(path)
        self._temp_sources.append(p)
        return str(p)

    def rebuild(self) -> pymupdf.Document:
        """Apply page_ops to a temp copy; return the scratch document."""
        self._drop_scratch()
        self.inserted_pages.clear()
        if not self.page_ops:
            return pymupdf.open(self.source)
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        shutil.copy(self.source, path)
        for op in self.page_ops:
            engine.apply(path, [op], output=path)
        self.scratch_path = path
        doc = pymupdf.open(path)
        self.inserted_pages = self._mark_inserted_pages(doc)
        return doc

    def open_view(self) -> pymupdf.Document:
        if self.scratch_path and os.path.exists(self.scratch_path):
            return pymupdf.open(self.scratch_path)
        if self.page_ops:
            return self.rebuild()
        return pymupdf.open(self.source)

    def page_count(self) -> int:
        doc = self.open_view()
        try:
            return doc.page_count
        finally:
            doc.close()

    def append_op(self, op: dict):
        self.page_ops.append(op)
        self.rebuild()

    def add_delete_pages(self, pages: list[int]):
        self.append_op({"op": "delete_pages", "pages": sorted(set(pages))})

    def add_rotate_pages(self, pages: list[int], degrees: int):
        self.append_op({"op": "rotate_pages", "pages": pages, "degrees": degrees})

    def add_crop_pages(self, pages: list[int], rect: list[float]):
        self.append_op({"op": "crop_pages", "pages": pages, "rect": rect})

    def add_move_pages(self, pages: list[int], after: int):
        self.append_op({"op": "move_pages", "pages": pages, "after": after})

    def add_insert_blank(self, after: int, count: int = 1, width: float = 595, height: float = 842):
        self.append_op(
            {
                "op": "insert_pages",
                "after": after,
                "blank": {"count": count, "width": width, "height": height},
            }
        )

    def add_insert_pdf(
        self,
        after: int,
        source: str,
        source_pages: list[int] | None = None,
        *,
        retain_source: bool = False,
    ):
        src = self._remember_source(source) if retain_source else source
        op: dict = {"op": "insert_pages", "after": after, "source": src}
        if source_pages:
            op["source_pages"] = source_pages
        self.append_op(op)

    def add_insert_image(self, after: int, image: str):
        self.append_op({"op": "insert_pages", "after": after, "image": image})

    def move_selection_to_after(self, selected_1based: list[int], after: int):
        if not selected_1based:
            return
        self.add_move_pages(selected_1based, after)

    def _mark_inserted_pages(self, doc: pymupdf.Document) -> set[int]:
        """Pages whose text does not match the original PAGE N labels are inserts."""
        orig = pymupdf.open(self.source)
        try:
            orig_labels = {
                n + 1: (orig[n].get_text("text").strip().split()[-1] if orig[n].get_text("text").strip() else "")
                for n in range(orig.page_count)
            }
        finally:
            orig.close()
        inserted: set[int] = set()
        for n in range(doc.page_count):
            text = doc[n].get_text("text").strip()
            label = text.split()[-1] if text else ""
            if str(n + 1) not in orig_labels.values() and label not in orig_labels.values():
                inserted.add(n + 1)
            elif text == "":
                inserted.add(n + 1)
        # Also tag pages beyond original count when labels still line up
        orig_count = len(orig_labels)
        for n in range(orig_count + 1, doc.page_count + 1):
            inserted.add(n)
        return inserted
