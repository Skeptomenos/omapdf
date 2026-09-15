"""Single unsaved-edit gate for Share, extract, copy, cut, and drag-export.

Share already refused while ghosts or page-surgery were pending. Page export
paths serialized the unredacted scratch document; they now use this same
predicate so a visible redaction ghost cannot leak bytes.
"""

from __future__ import annotations

from .page_clipboard import extract_pages_bytes, serialize_pages, write_pages_to_file


class UnsavedExport(Exception):
    """Outbound PDF bytes were blocked because the editor still has unsaved work."""


def unsaved_export_reason(
    pending,
    preview_dirty: bool,
    *,
    action: str = "sharing",
) -> str | None:
    if pending or preview_dirty:
        return f"Unsaved changes — Save before {action}"
    return None


def require_clean_export(pending, preview_dirty: bool, *, action: str) -> None:
    reason = unsaved_export_reason(pending, preview_dirty, action=action)
    if reason:
        raise UnsavedExport(reason)


def extract_pages_bytes_if_clean(pending, preview_dirty: bool, doc, pages) -> bytes:
    require_clean_export(pending, preview_dirty, action="exporting pages")
    return extract_pages_bytes(doc, pages)


def serialize_pages_if_clean(pending, preview_dirty: bool, doc, pages) -> tuple[bytes, bytes]:
    require_clean_export(pending, preview_dirty, action="exporting pages")
    return serialize_pages(doc, pages)


def write_pages_if_clean(pending, preview_dirty: bool, doc, pages, dest) -> None:
    require_clean_export(pending, preview_dirty, action="exporting pages")
    write_pages_to_file(doc, pages, dest)
