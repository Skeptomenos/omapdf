"""omepreview MCP server — the agent's native doorway.

Every tool here is a thin wrapper over the same op engine the CLI and GUI
use; nothing is agent-only or human-only. Run with `omepreview-mcp` (stdio), or
register with Claude Code:

    claude mcp add omepreview -- omepreview-mcp

Safety posture: place_signature defaults to a dry run that returns the
resolved placement rectangle for confirmation. Pass confirmed=true (after a
human has approved the placement, or when the user has explicitly delegated
signing) to write it.
"""

from __future__ import annotations

try:  # MCP SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK v1
    from mcp.server.fastmcp import FastMCP as _Server

from . import engine, pages as pages_mod, read, signature

mcp = _Server("omepreview")


@mcp.tool()
def read_pdf(path: str, pages: list[int] | None = None, text_only: bool = False) -> dict:
    """Read a PDF's structure: pages, text blocks with bounding boxes, form
    fields, and annotations. Coordinates are PDF points, origin top-left —
    the same system every other omepreview tool accepts."""
    return read.extract(path, pages=pages, text_only=text_only)


@mcp.tool()
def list_form_fields(path: str) -> list[dict]:
    """List every form field (name, type, current value, page, rect)."""
    return read.form_fields(path)


@mcp.tool()
def apply_ops(path: str, ops: list[dict], output: str | None = None, dry_run: bool = False) -> dict:
    """Apply a list of operations (highlight, note, text_box, fill_field,
    place_signature) in one atomic edit. See omapdf's ops spec. Prefer this
    over many single calls when making several edits."""
    return engine.apply(path, ops, output=output, dry_run=dry_run)


@mcp.tool()
def highlight(path: str, page: int, match: str, style: str = "highlight", output: str | None = None) -> dict:
    """Highlight (or underline/strikeout/squiggly) every occurrence of
    `match` on `page`."""
    return engine.apply(
        path, [{"op": "highlight", "page": page, "match": match, "style": style}], output=output
    )


@mcp.tool()
def add_note(path: str, page: int, x: float, y: float, text: str, output: str | None = None) -> dict:
    """Attach a sticky-note comment at (x, y) on `page`."""
    return engine.apply(
        path, [{"op": "note", "page": page, "at": [x, y], "text": text}], output=output
    )


@mcp.tool()
def fill_field(path: str, field: str, value: str, output: str | None = None) -> dict:
    """Fill one form field by name. Errors list the document's real field
    names if the name doesn't match."""
    return engine.apply(
        path, [{"op": "fill_field", "field": field, "value": value}], output=output
    )


@mcp.tool()
def place_signature(
    path: str,
    page: int,
    x: float,
    y: float,
    width: float = 180,
    signature_name: str = "default",
    date: bool = False,
    confirmed: bool = False,
    output: str | None = None,
) -> dict:
    """Place the user's saved signature with its top-left corner at (x, y).

    By default this is a DRY RUN returning the resolved placement rect —
    show it to the user (or open the PDF) and call again with confirmed=true
    once approved. Signing a document is consequential: never set
    confirmed=true without the user's go-ahead."""
    op = {
        "op": "place_signature",
        "page": page,
        "at": [x, y],
        "width": width,
        "signature": signature_name,
        "date": date,
    }
    result = engine.apply(path, [op], output=output, dry_run=not confirmed)
    if not confirmed:
        result["needs_confirmation"] = (
            "Dry run only. Re-call with confirmed=true after the user approves this placement."
        )
    return result


@mcp.tool()
def list_signatures() -> list[str]:
    """Names of the user's saved signatures (SVG in ~/Downloads/omapreview/signature/; also reads ~/.config/omepreview/signatures/)."""
    return signature.list_names()


@mcp.tool()
def list_pages(path: str) -> dict:
    """List every page in a PDF with number, size, and rotation."""
    return pages_mod.list_pages(path)


@mcp.tool()
def delete_pages(
    path: str,
    pages: list[int],
    output: str | None = None,
    confirm: bool = False,
) -> dict:
    """Delete pages by 1-based number. Defaults to dry-run — pass confirm=true
    after the user approves."""
    result = engine.apply(
        path,
        [{"op": "delete_pages", "pages": pages}],
        output=output,
        dry_run=not confirm,
    )
    if not confirm:
        result["needs_confirmation"] = (
            "Dry run only. Re-call with confirm=true after the user approves."
        )
    return result


@mcp.tool()
def rotate_pages(
    path: str,
    pages: list[int],
    degrees: int,
    output: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Rotate pages by 90, 180, 270, or -90 degrees."""
    return engine.apply(
        path,
        [{"op": "rotate_pages", "pages": pages, "degrees": degrees}],
        output=output,
        dry_run=dry_run,
    )


@mcp.tool()
def move_pages(
    path: str,
    pages: list[int],
    after: int,
    output: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Reorder pages: move `pages` to after page `after` (0 = beginning)."""
    return engine.apply(
        path,
        [{"op": "move_pages", "pages": pages, "after": after}],
        output=output,
        dry_run=dry_run,
    )


@mcp.tool()
def insert_pages(
    path: str,
    after: int,
    output: str | None = None,
    source: str | None = None,
    source_pages: list[int] | None = None,
    blank_count: int | None = None,
    blank_width: float = 595,
    blank_height: float = 842,
    image: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Insert pages after `after` from a source PDF, blank sheet(s), or image."""
    op: dict = {"op": "insert_pages", "after": after}
    if source:
        op["source"] = source
        if source_pages:
            op["source_pages"] = source_pages
    elif image:
        op["image"] = image
    elif blank_count is not None:
        op["blank"] = {
            "count": blank_count,
            "width": blank_width,
            "height": blank_height,
        }
    else:
        raise ValueError("insert_pages needs source, image, or blank_count")
    return engine.apply(path, [op], output=output, dry_run=dry_run)


@mcp.tool()
def extract_pages(
    path: str,
    pages: list[int],
    to: str,
    dry_run: bool = False,
) -> dict:
    """Write selected pages to a new PDF at `to`. The source file is unchanged."""
    return engine.apply(
        path,
        [{"op": "extract_pages", "pages": pages, "to": to}],
        dry_run=dry_run,
    )


@mcp.tool()
def delete_annotation(
    path: str,
    page: int,
    index: int,
    output: str | None = None,
    confirm: bool = False,
) -> dict:
    """Delete one annotation on `page` by 0-based `index` (see omepreview read).

    Defaults to dry-run — pass confirm=true after the user approves."""
    result = engine.apply(
        path,
        [{"op": "delete_annotation", "page": page, "index": index}],
        output=output,
        dry_run=not confirm,
    )
    if not confirm:
        result["needs_confirmation"] = (
            "Dry run only. Re-call with confirm=true after the user approves."
        )
    return result


@mcp.tool()
def redact(
    path: str,
    page: int,
    match: str | None = None,
    rect: list[float] | None = None,
    fill: list[float] | None = None,
    output: str | None = None,
    confirm: bool = False,
) -> dict:
    """Permanently remove text or image pixels in a region on `page`.

    Provide exactly one of `match` (text search) or `rect` ([x0,y0,x1,y1]).
    Defaults to dry-run — pass confirm=true after the user approves."""
    op: dict = {"op": "redact", "page": page}
    if match:
        op["match"] = match
    elif rect:
        op["rect"] = rect
    else:
        raise ValueError("redact needs match or rect")
    if fill:
        op["fill"] = fill
    result = engine.apply(path, [op], output=output, dry_run=not confirm)
    if not confirm:
        result["needs_confirmation"] = (
            "Dry run only. Re-call with confirm=true after the user approves."
        )
    return result


@mcp.tool()
def crop_pages(
    path: str,
    pages: list[int],
    rect: list[float],
    output: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Set the PDF CropBox for ``pages`` to ``rect`` ([x0, y0, x1, y1] in the
    page's current coordinate space, top-left origin). Does not trim content —
    it changes the visible page box."""
    return engine.apply(
        path,
        [{"op": "crop_pages", "pages": pages, "rect": rect}],
        output=output,
        dry_run=dry_run,
    )


@mcp.tool()
def add_shape(
    path: str,
    page: int,
    shape: str,
    from_point: list[float] | None = None,
    to_point: list[float] | None = None,
    rect: list[float] | None = None,
    color: list[float] | None = None,
    width: float = 2.0,
    output: str | None = None,
) -> dict:
    """Add a Line, Square, or Circle PDF annotation on `page`.

    `shape` is one of line, arrow, rect, oval. Line and arrow need
    `from_point` and `to_point` ([x, y]); rect and oval need `rect`
    ([x0, y0, x1, y1]). Coordinates are PDF points, top-left origin."""
    op: dict = {"op": "shape", "page": page, "shape": shape, "width": width}
    if shape in ("line", "arrow"):
        if not from_point or not to_point:
            raise ValueError("line and arrow need from_point and to_point")
        op["from"] = from_point
        op["to"] = to_point
    elif rect:
        op["rect"] = rect
    else:
        raise ValueError("rect and oval need rect")
    if color:
        op["color"] = color
    return engine.apply(path, [op], output=output)


@mcp.tool()
def flatten_pdf(path: str, output: str | None = None) -> dict:
    """Bake all annotations and form fields into page content (irreversible
    in the output file; the input is preserved when `output` is given)."""
    return engine.flatten(path, output=output)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
