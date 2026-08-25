"""omapdf MCP server — the agent's native doorway.

Every tool here is a thin wrapper over the same op engine the CLI and GUI
use; nothing is agent-only or human-only. Run with `omapdf-mcp` (stdio), or
register with Claude Code:

    claude mcp add omapdf -- omapdf-mcp

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

from . import engine, read, signature

mcp = _Server("omapdf")


@mcp.tool()
def read_pdf(path: str, pages: list[int] | None = None, text_only: bool = False) -> dict:
    """Read a PDF's structure: pages, text blocks with bounding boxes, form
    fields, and annotations. Coordinates are PDF points, origin top-left —
    the same system every other omapdf tool accepts."""
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
    """Names of the user's saved signature images."""
    return signature.list_names()


@mcp.tool()
def flatten_pdf(path: str, output: str | None = None) -> dict:
    """Bake all annotations and form fields into page content (irreversible
    in the output file; the input is preserved when `output` is given)."""
    return engine.flatten(path, output=output)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
