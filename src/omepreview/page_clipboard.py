"""Cross-window page clipboard serialization for the GTK editor."""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

import pymupdf

MIME_OMEPREVIEW_PAGES = "application/x-omepreview-pages"
MIME_OMAPDF_PAGES = "application/x-omapdf-pages"  # deprecated; accepted on paste
MIME_PDF = "application/pdf"
PAGE_CLIPBOARD_MIMES = (MIME_OMEPREVIEW_PAGES, MIME_OMAPDF_PAGES)


def extract_pages_bytes(doc: pymupdf.Document, pages_1based: list[int]) -> bytes:
    """Build a PDF containing ``pages_1based`` from ``doc``."""
    if not pages_1based:
        raise ValueError("no pages selected")
    out = pymupdf.open()
    try:
        for p in pages_1based:
            if p < 1 or p > doc.page_count:
                raise ValueError(f"page {p} out of range (document has {doc.page_count})")
            out.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
        return out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()


def serialize_pages(doc: pymupdf.Document, pages_1based: list[int]) -> tuple[bytes, bytes]:
    """Return ``(json_bytes, pdf_bytes)`` for the clipboard."""
    pdf_bytes = extract_pages_bytes(doc, pages_1based)
    payload = {
        "n": len(pages_1based),
        "pdf_b64": base64.standard_b64encode(pdf_bytes).decode("ascii"),
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8"), pdf_bytes


def pdf_bytes_from_clipboard_text(text: str) -> bytes | None:
    """Parse ``application/x-omepreview-pages`` JSON payload (legacy MIME too)."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    b64 = payload.get("pdf_b64")
    if not isinstance(b64, str):
        return None
    try:
        return base64.standard_b64decode(b64.encode("ascii"))
    except (ValueError, json.JSONDecodeError):
        return None


def write_temp_pdf(pdf_bytes: bytes) -> Path:
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with open(fd, "wb") as fh:
            fh.write(pdf_bytes)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return Path(path)


def write_pages_to_file(doc: pymupdf.Document, pages_1based: list[int], dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(extract_pages_bytes(doc, pages_1based))
    return dest


def push_clipboard(json_bytes: bytes, pdf_bytes: bytes) -> None:
    """Write omepreview pages to the system clipboard (GTK + xclip on X11)."""
    import shutil
    import subprocess

    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, GLib

        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(
                Gdk.ContentProvider.new_union([
                    Gdk.ContentProvider.new_for_bytes(
                        MIME_OMEPREVIEW_PAGES, GLib.Bytes.new(json_bytes)
                    ),
                    Gdk.ContentProvider.new_for_bytes(
                        MIME_PDF, GLib.Bytes.new(pdf_bytes)
                    ),
                ])
            )
    except (ImportError, ValueError):
        pass
    if shutil.which("xclip"):
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", MIME_OMEPREVIEW_PAGES],
            input=json_bytes,
            check=False,
        )


def read_clipboard_pdf_bytes() -> bytes | None:
    """Read omepreview page bytes from the system clipboard (xclip + GTK)."""
    import shutil
    import subprocess

    readers = []
    if shutil.which("xclip"):
        readers.append(_read_xclip)
    readers.append(_read_gtk_clipboard_mime)
    for mime in (*PAGE_CLIPBOARD_MIMES, MIME_PDF):
        for read in readers:
            data = read(mime)
            if not data:
                continue
            if mime in PAGE_CLIPBOARD_MIMES:
                pdf = pdf_bytes_from_clipboard_text(data.decode("utf-8", errors="replace"))
                if pdf:
                    return pdf
            else:
                return data
    return None


def _read_xclip(mime: str) -> bytes | None:
    import subprocess

    proc = subprocess.run(
        ["xclip", "-selection", "clipboard", "-t", mime, "-o"],
        capture_output=True,
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _read_gtk_clipboard_mime(mime: str) -> bytes | None:
    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, GLib
    except (ImportError, ValueError):
        return None
    display = Gdk.Display.get_default()
    if display is None:
        return None
    clip = display.get_clipboard()
    if clip is None:
        return None
    result: dict[str, bytes | None] = {"val": None, "done": False}

    def done(_clipboard, res):
        try:
            val = _clipboard.read_value_finish(res)
            if isinstance(val, GLib.Bytes):
                result["val"] = val.get_data()
            elif isinstance(val, (bytes, bytearray)):
                result["val"] = bytes(val)
            elif isinstance(val, str):
                result["val"] = val.encode("utf-8")
        except GLib.Error:
            pass
        result["done"] = True

    clip.read_value_async(mime, GLib.PRIORITY_DEFAULT, None, done)
    ctx = GLib.MainContext.default()
    while not result["done"]:
        while ctx.iteration(True):
            pass
    return result["val"]
