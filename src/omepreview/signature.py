"""Signature store: named SVG (or imported PNG) files in the user's config dir.

Recorded signatures are SVG. `place_signature` and the Sign tool consume SVG
(and still open a leftover PNG if one exists). Files live in
~/.config/omepreview/signatures/. The name "default" is what `place_signature`
uses when no name is given.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_SUFFIXES = (".svg", ".png")


def store_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "omepreview" / "signatures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(name: str) -> Path:
    if "/" in name or name.startswith("."):
        raise ValueError(f"invalid signature name {name!r}")
    svg = store_dir() / f"{name}.svg"
    png = store_dir() / f"{name}.png"
    if svg.is_file() or not png.is_file():
        return svg
    return png


def add(source: str | Path, name: str = "default") -> Path:
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"no such image: {source}")
    suffix = source.suffix.lower()
    if suffix not in _SUFFIXES:
        raise ValueError(
            "signatures must be SVG (recorder default) or PNG to import"
        )
    dest = store_dir() / f"{name}{suffix}"
    shutil.copyfile(source, dest)
    other = ".png" if suffix == ".svg" else ".svg"
    (store_dir() / f"{name}{other}").unlink(missing_ok=True)
    return dest


def get(name: str = "default") -> Path:
    p = path_for(name)
    if not p.is_file():
        known = ", ".join(list_names()) or "(none saved)"
        raise FileNotFoundError(
            f"no signature named {name!r}. Saved signatures: {known}. "
            f"Add one with: omepreview sig draw --name {name}"
        )
    return p


def list_names() -> list[str]:
    names: set[str] = set()
    for p in store_dir().iterdir():
        if p.is_file() and p.suffix.lower() in _SUFFIXES:
            names.add(p.stem)
    return sorted(names)


def remove(name: str) -> None:
    svg = store_dir() / f"{name}.svg"
    png = store_dir() / f"{name}.png"
    if not svg.is_file() and not png.is_file():
        path_for(name).unlink(missing_ok=False)
        return
    svg.unlink(missing_ok=True)
    png.unlink(missing_ok=True)


def aspect_ratio(path: str | Path) -> float:
    """Height / width of a stored signature (SVG viewBox or PNG pixels)."""
    import pymupdf

    path = Path(path)
    if path.suffix.lower() == ".svg":
        doc = pymupdf.open(path)
        try:
            rect = doc[0].rect
            return rect.height / rect.width if rect.width else 0.4
        finally:
            doc.close()
    pix = pymupdf.Pixmap(str(path))
    return pix.height / pix.width if pix.width else 0.4


def rasterize(path: str | Path, *, dpi: int = 180):
    """Pixmap of an SVG or PNG signature (alpha preserved when the file has it)."""
    import pymupdf

    path = Path(path)
    if path.suffix.lower() == ".svg":
        doc = pymupdf.open(path)
        try:
            return doc[0].get_pixmap(alpha=True, dpi=dpi)
        finally:
            doc.close()
    return pymupdf.Pixmap(str(path))


def insert_on_page(page, rect, path: str | Path) -> None:
    """Stamp a stored signature onto a PDF page, preferring vector SVG."""
    import pymupdf

    path = Path(path)
    if path.suffix.lower() == ".svg":
        src = pymupdf.open(path)
        try:
            pdfbytes = src.convert_to_pdf()
        finally:
            src.close()
        overlay = pymupdf.open("pdf", pdfbytes)
        try:
            page.show_pdf_page(rect, overlay, 0, keep_proportion=True)
        finally:
            overlay.close()
        return
    page.insert_image(rect, filename=str(path), keep_proportion=True)
