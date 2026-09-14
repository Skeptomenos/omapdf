"""Generated PDF fixtures for page-op tests.

Builds labeled multi-page PDFs at runtime — no committed binaries.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def make_labeled_pdf(
    path: Path | str,
    page_count: int = 6,
    label_prefix: str = "PAGE",
) -> Path:
    """Write a PDF with one text label per page: 'PAGE 1', 'PAGE 2', …"""
    path = Path(path)
    doc = pymupdf.open()
    for n in range(1, page_count + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"{label_prefix} {n}", fontsize=24)
    doc.save(str(path))
    doc.close()
    return path


def make_image_asset(path: Path | str, width: int = 200, height: int = 150) -> Path:
    """Small PNG for image-as-page insert tests."""
    path = Path(path)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.set_rect(pymupdf.IRect(20, 20, width - 20, height - 20), (51, 128, 230))
    pix.save(str(path))
    return path


def make_image_only_page_pdf(path: Path | str, image_path: Path | str) -> Path:
    """Single-page PDF whose only content is a full-page raster image."""
    path = Path(path)
    image_path = Path(image_path)
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(str(image_path))
    page = doc.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, filename=str(image_path))
    doc.save(str(path))
    doc.close()
    return path
