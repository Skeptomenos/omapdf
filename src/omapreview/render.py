"""Render pages to images — including the agent's coordinate grid.

snapshot() draws an optional labeled grid in PDF-point coordinates over the
page before rasterizing. An agent (or human) can look at the image and read
off exactly the numbers that place_signature / text_box / ink expect, since
the grid IS the ops coordinate system.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

GRID_COLOR = (0.85, 0.2, 0.2)


def snapshot(
    pdf: str | Path,
    page: int = 1,
    output: str | Path | None = None,
    grid: float | None = None,
    scale: float = 2.0,
) -> dict:
    """Render `page` (1-based) to PNG. grid=N overlays labeled lines every N
    points. Returns {"output", "page", "size": [w, h] in points}."""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise FileNotFoundError(f"no such PDF: {pdf}")
    doc = pymupdf.open(str(pdf))
    try:
        if page < 1 or page > doc.page_count:
            raise ValueError(f"page {page} out of range (document has {doc.page_count})")
        pg = doc[page - 1]
        size = [pg.rect.width, pg.rect.height]

        if grid:
            _draw_grid(pg, grid)

        if output is None:
            suffix = f"-p{page}-grid.png" if grid else f"-p{page}.png"
            output = pdf.with_name(pdf.stem + suffix)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        pix.save(str(output))
        return {"output": str(output), "page": page, "size": size}
    finally:
        doc.close()


def _draw_grid(pg: pymupdf.Page, step: float) -> None:
    width, height = pg.rect.width, pg.rect.height
    shape = pg.new_shape()

    x = step
    while x < width:
        shape.draw_line((x, 0), (x, height))
        x += step
    y = step
    while y < height:
        shape.draw_line((0, y), (width, y))
        y += step
    shape.finish(color=GRID_COLOR, width=0.4, stroke_opacity=0.55)
    shape.commit()

    # Labels on both edges so a crop of the image still carries coordinates.
    x = step
    while x < width:
        for ly in (10, height - 4):
            pg.insert_text((x + 1, ly), str(int(x)), fontsize=6, color=GRID_COLOR)
        x += step
    y = step
    while y < height:
        for lx in (2, width - 22):
            pg.insert_text((lx, y - 1), str(int(y)), fontsize=6, color=GRID_COLOR)
        y += step
