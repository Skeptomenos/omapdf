"""Apply operation lists to PDFs.

This is the single write-path for the whole project: the CLI, the MCP server,
and (eventually) the GUI all funnel edits through apply(). Every applied op is
echoed back in a report with its resolved geometry, so callers — human or
agent — can show exactly what changed and where.
"""

from __future__ import annotations

import datetime
import os
import tempfile
from pathlib import Path

import pymupdf

from . import ops as ops_mod
from . import signature as sig_store
from .ops import OpError


def _page(doc: pymupdf.Document, number: int) -> pymupdf.Page:
    if number < 1 or number > doc.page_count:
        raise OpError(f"page {number} out of range (document has {doc.page_count})")
    return doc[number - 1]


def _apply_highlight(doc, op) -> dict:
    page = _page(doc, op["page"])
    if "match" in op:
        rects = page.search_for(op["match"])
        if not rects:
            raise OpError(
                f"text {op['match']!r} not found on page {op['page']}; "
                "run `omapdf read` to see the page's actual text"
            )
    else:
        rects = [pymupdf.Rect(op["rect"])]

    add = {
        "highlight": page.add_highlight_annot,
        "underline": page.add_underline_annot,
        "strikeout": page.add_strikeout_annot,
        "squiggly": page.add_squiggly_annot,
    }[op["style"]]
    for rect in rects:
        annot = add(rect)
        annot.update()
    return {"rects": [list(r) for r in rects]}


def _apply_note(doc, op) -> dict:
    page = _page(doc, op["page"])
    annot = page.add_text_annot(pymupdf.Point(op["at"]), op["text"])
    annot.update()
    return {"at": op["at"]}


def _apply_text_box(doc, op) -> dict:
    page = _page(doc, op["page"])
    rect = pymupdf.Rect(op["rect"])
    annot = page.add_freetext_annot(
        rect, op["text"], fontsize=op["size"], fontname="helv", text_color=(0, 0, 0)
    )
    annot.update()
    return {"rect": list(rect)}


def _apply_fill_field(doc, op) -> dict:
    name, value = op["field"], op["value"]
    for page in doc:
        for widget in page.widgets():
            if widget.field_name != name:
                continue
            if widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                widget.field_value = str(value).lower() in ("true", "yes", "on", "1")
            else:
                widget.field_value = str(value)
            widget.update()
            return {"field": name, "page": page.number + 1}
    known = sorted(
        w.field_name for p in doc for w in p.widgets() if w.field_name
    )
    raise OpError(
        f"no form field named {name!r}. Fields in this document: "
        f"{', '.join(known) if known else '(none — this PDF has no form)'}"
    )


def _apply_place_signature(doc, op) -> dict:
    page = _page(doc, op["page"])
    png = sig_store.get(op["signature"])
    pix = pymupdf.Pixmap(str(png))
    if pix.width == 0 or pix.height == 0:
        raise OpError(f"signature image {png} is empty")
    width = op["width"]
    height = width * pix.height / pix.width
    x, y = op["at"]
    rect = pymupdf.Rect(x, y, x + width, y + height)
    page.insert_image(rect, filename=str(png), keep_proportion=True)

    result = {"rect": list(rect), "signature": op["signature"]}
    if op["date"]:
        date_str = datetime.date.today().isoformat()
        page.insert_text(
            pymupdf.Point(x, y + height + 12), date_str, fontsize=10, fontname="helv"
        )
        result["date"] = date_str
    return result


def _apply_ink(doc, op) -> dict:
    page = _page(doc, op["page"])
    annot = page.add_ink_annot(op["strokes"])
    annot.set_colors(stroke=op["color"])
    annot.set_border(width=op["width"])
    annot.update()
    return {"rect": list(annot.rect)}


_APPLIERS = {
    "highlight": _apply_highlight,
    "note": _apply_note,
    "text_box": _apply_text_box,
    "fill_field": _apply_fill_field,
    "place_signature": _apply_place_signature,
    "ink": _apply_ink,
}


def _save(doc: pymupdf.Document, source: Path, output: Path) -> None:
    # PyMuPDF cannot do a full (garbage-collected) save over the file it has
    # open, so route same-file saves through a sibling temp file.
    if output.resolve() == source.resolve():
        fd, tmp = tempfile.mkstemp(dir=str(output.parent), suffix=".pdf")
        os.close(fd)
        try:
            doc.save(tmp, garbage=3, deflate=True)
            doc.close()
            os.replace(tmp, output)
        except BaseException:
            os.unlink(tmp)
            raise
    else:
        doc.save(str(output), garbage=3, deflate=True)
        doc.close()


def apply(
    pdf: str | Path,
    op_list: list[dict],
    output: str | Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Validate and apply ops to `pdf`, writing `output` (default: in place).

    Returns {"output": path|None, "applied": [op ⊕ resolution, ...]}.
    With dry_run=True nothing is written; the report still resolves geometry
    (text matches, signature rects) so callers can preview placements.
    """
    pdf = Path(pdf)
    if not pdf.is_file():
        raise FileNotFoundError(f"no such PDF: {pdf}")
    validated = ops_mod.validate_all(op_list)
    output = Path(output) if output else pdf

    doc = pymupdf.open(str(pdf))
    try:
        if doc.needs_pass:
            raise OpError(f"{pdf} is password-protected; decrypt it first")
        applied = []
        for op in validated:
            resolution = _APPLIERS[op["op"]](doc, op)
            applied.append({**op, **resolution, "applied": not dry_run})
        if dry_run:
            doc.close()
            return {"output": None, "applied": applied}
        _save(doc, pdf, output)
    except BaseException:
        if not doc.is_closed:
            doc.close()
        raise
    return {"output": str(output), "applied": applied}


def flatten(pdf: str | Path, output: str | Path | None = None) -> dict:
    """Bake annotations and form fields into page content.

    Use before sending to recipients whose viewers mishandle annotations, or
    to make filled forms and placed marks non-editable.
    """
    pdf = Path(pdf)
    if not pdf.is_file():
        raise FileNotFoundError(f"no such PDF: {pdf}")
    output = Path(output) if output else pdf
    doc = pymupdf.open(str(pdf))
    try:
        doc.bake(annots=True, widgets=True)
        _save(doc, pdf, output)
    except BaseException:
        if not doc.is_closed:
            doc.close()
        raise
    return {"output": str(output)}
