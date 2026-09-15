"""Scope of region redaction beyond page text (OMP-04).

An authorized redact rectangle covers extractable page text **and**
intersecting annotation/widget payloads. Known types are stripped in the
same op. Unsupported intersecting types fail closed so success never leaves
a recoverable secret. Objects outside the rectangle are left intact.

Does not apply unrelated pending PDF redaction annotations (R14 / OMP-05).
"""

from __future__ import annotations

import pymupdf

from .ops import OpError

# Sticky notes, replies (usually Text), FreeText, file attachments, popups
# (dependents of notes), and form widgets. Anything else intersecting the
# authorized rectangle is refused.
_KNOWN_ANNOT_TYPES = {
    pymupdf.PDF_ANNOT_TEXT,
    pymupdf.PDF_ANNOT_FREE_TEXT,
    pymupdf.PDF_ANNOT_FILE_ATTACHMENT,
    pymupdf.PDF_ANNOT_POPUP,
    pymupdf.PDF_ANNOT_WIDGET,
}


def _as_rect(rect) -> pymupdf.Rect:
    return rect if isinstance(rect, pymupdf.Rect) else pymupdf.Rect(rect)


def intersects_any(rect, rects: list) -> bool:
    r = _as_rect(rect)
    return any(r.intersects(_as_rect(other)) for other in rects)


def _type_id(annot) -> int:
    return int(annot.type[0])


def _type_name(annot) -> str:
    return str(annot.type[1])


def unsupported_intersecting(page: pymupdf.Page, rects: list) -> list[str]:
    """Type names of intersecting annots that region redact cannot strip."""
    names: list[str] = []
    seen: set[int] = set()
    for annot in page.annots() or []:
        if _type_id(annot) == pymupdf.PDF_ANNOT_WIDGET:
            continue
        if _type_id(annot) in _KNOWN_ANNOT_TYPES:
            continue
        if annot.xref in seen:
            continue
        if intersects_any(annot.rect, rects):
            seen.add(annot.xref)
            names.append(_type_name(annot))
    return names


def fail_closed_if_unsupported(page: pymupdf.Page, rects: list, *, page_no: int) -> None:
    names = unsupported_intersecting(page, rects)
    if not names:
        return
    listed = ", ".join(sorted(set(names)))
    raise OpError(
        f"redact refused: page {page_no} has intersecting {listed} "
        "annotation(s) that region redact cannot strip. Delete those "
        "annotations first, or shrink the rectangle so it does not cover them."
    )


def _popup_xrefs(annot) -> set[int]:
    xref = getattr(annot, "popup_xref", 0) or 0
    return {xref} if xref else set()


def _thread_xrefs(page: pymupdf.Page, seed: set[int]) -> set[int]:
    """Expand to replies (IRT) and popups of every xref in the set."""
    owned = set(seed)
    changed = True
    while changed:
        changed = False
        for annot in page.annots() or []:
            extra: set[int] = set()
            if annot.xref in owned:
                extra |= _popup_xrefs(annot)
            irt = getattr(annot, "irt_xref", 0) or 0
            if irt in owned:
                extra.add(annot.xref)
                extra |= _popup_xrefs(annot)
            if extra - owned:
                owned |= extra
                changed = True
    return owned


def xrefs_to_strip(page: pymupdf.Page, rects: list) -> set[int]:
    """Xrefs of known annots in *rects*, plus their replies and popups."""
    seed: set[int] = set()
    for annot in page.annots() or []:
        kind = _type_id(annot)
        if kind == pymupdf.PDF_ANNOT_WIDGET:
            continue
        if kind not in _KNOWN_ANNOT_TYPES:
            continue
        if intersects_any(annot.rect, rects):
            seed.add(annot.xref)
            seed |= _popup_xrefs(annot)
    return _thread_xrefs(page, seed)


def _delete_annots_xrefs(page: pymupdf.Page, xrefs: set[int]) -> int:
    deleted = 0
    remaining = set(xrefs)
    while remaining:
        victim = None
        for annot in page.annots() or []:
            if annot.xref in remaining:
                victim = annot
                break
        if victim is None:
            break
        remaining.discard(victim.xref)
        page.delete_annot(victim)
        deleted += 1
    return deleted


def _delete_widgets_in_rects(page: pymupdf.Page, rects: list) -> int:
    deleted = 0
    while True:
        victim = None
        for widget in page.widgets() or []:
            if intersects_any(widget.rect, rects):
                victim = widget
                break
        if victim is None:
            break
        page.delete_widget(victim)
        deleted += 1
    return deleted


def strip_known_in_rects(page: pymupdf.Page, rects: list) -> dict:
    """Remove known in-rect annots/widgets (and note reply threads)."""
    xrefs = xrefs_to_strip(page, rects)
    n_annots = _delete_annots_xrefs(page, xrefs)
    n_widgets = _delete_widgets_in_rects(page, rects)
    return {"annotations": n_annots, "widgets": n_widgets}


def _annot_payload(annot) -> str:
    content = (annot.info or {}).get("content") or ""
    if _type_id(annot) == pymupdf.PDF_ANNOT_FILE_ATTACHMENT:
        try:
            data = annot.get_file() or b""
        except Exception:
            data = b""
        extra = data.decode("utf-8", "replace") if data else ""
        info = {}
        try:
            info = annot.file_info or {}
        except Exception:
            pass
        name = info.get("filename") or ""
        return " ".join(p for p in (content, name, extra) if p)
    return content


def _widget_payload(widget) -> str:
    value = widget.field_value
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    return str(value).strip()


def intersecting_payloads(page: pymupdf.Page, rects: list) -> list[str]:
    """Human-readable leftovers still sitting in the authorized rectangle."""
    leftovers: list[str] = []
    for annot in page.annots() or []:
        if _type_id(annot) == pymupdf.PDF_ANNOT_WIDGET:
            continue
        if not intersects_any(annot.rect, rects):
            continue
        payload = _annot_payload(annot).strip()
        leftovers.append(
            f"{_type_name(annot)}"
            + (f" {payload!r}" if payload else "")
        )
    for widget in page.widgets() or []:
        if not intersects_any(widget.rect, rects):
            continue
        payload = _widget_payload(widget)
        name = widget.field_name or ""
        leftovers.append(
            f"Widget {name!r}"
            + (f" {payload!r}" if payload else "")
        )
    return leftovers


def text_still_present(page: pymupdf.Page, match: str | None, rects: list) -> bool:
    if match is not None:
        return match in page.get_text()
    for rect in rects:
        if page.get_textbox(_as_rect(rect)).strip():
            return True
    return False


def verify_serialized(doc: pymupdf.Document, op: dict) -> None:
    """Fail closed if the reopened document still holds in-rect secrets."""
    page_no = int(op["page"])
    if page_no < 1 or page_no > doc.page_count:
        raise OpError(
            f"redact verify failed: page {page_no} missing after serialization"
        )
    page = doc[page_no - 1]
    rects = [pymupdf.Rect(r) for r in op["rects"]]
    match = op.get("match")
    if text_still_present(page, match, rects):
        raise OpError(
            f"redact verify failed on page {page_no}: text still present after "
            "redaction — widen the region or check for overlapping content"
        )
    leftovers = intersecting_payloads(page, rects)
    if leftovers:
        raise OpError(
            f"redact verify failed on page {page_no}: payloads still present "
            f"in the region after serialization: {', '.join(leftovers)}"
        )
