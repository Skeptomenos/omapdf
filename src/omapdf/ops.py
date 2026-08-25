"""The operation schema — the single vocabulary shared by every client.

An operation is a plain dict (JSON-friendly). A document edit is a list of
operations. The GUI, the CLI, and the MCP server all reduce to building one
of these lists and handing it to engine.apply().

Op reference (see docs/ops.md for the full spec):

  {"op": "highlight",  "page": 1, "match": "termination clause"}
  {"op": "highlight",  "page": 1, "rect": [x0, y0, x1, y1], "style": "underline"}
  {"op": "note",       "page": 2, "at": [x, y], "text": "Check this figure"}
  {"op": "text_box",   "page": 2, "rect": [x0, y0, x1, y1], "text": "N/A", "size": 11}
  {"op": "fill_field", "field": "tenant_name", "value": "Peter Bergin"}
  {"op": "place_signature", "page": 4, "at": [x, y], "width": 180,
   "signature": "default", "date": true}

Pages are 1-based everywhere a human or agent sees them. Coordinates are PDF
points (1/72 inch) with the origin at the TOP-LEFT of the page, matching what
`omapdf read` reports.
"""

from __future__ import annotations

MARKUP_STYLES = ("highlight", "underline", "strikeout", "squiggly")

OP_TYPES = ("highlight", "note", "text_box", "fill_field", "place_signature")


class OpError(ValueError):
    """An operation failed validation or could not be applied."""


def _require(op: dict, key: str):
    if key not in op:
        raise OpError(f"op '{op.get('op')}' missing required key '{key}': {op}")
    return op[key]


def _rect(value) -> list[float]:
    if not (isinstance(value, (list, tuple)) and len(value) == 4):
        raise OpError(f"rect must be [x0, y0, x1, y1], got {value!r}")
    return [float(v) for v in value]


def _point(value) -> list[float]:
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise OpError(f"point must be [x, y], got {value!r}")
    return [float(v) for v in value]


def validate(op: dict) -> dict:
    """Validate one op, returning a normalized copy. Raises OpError."""
    if not isinstance(op, dict):
        raise OpError(f"each op must be an object, got {type(op).__name__}")
    kind = op.get("op")
    if kind not in OP_TYPES:
        raise OpError(f"unknown op {kind!r}; valid ops: {', '.join(OP_TYPES)}")
    out = dict(op)

    if kind == "highlight":
        _require(op, "page")
        if ("match" in op) == ("rect" in op):
            raise OpError("highlight needs exactly one of 'match' or 'rect'")
        if "rect" in op:
            out["rect"] = _rect(op["rect"])
        style = op.get("style", "highlight")
        if style not in MARKUP_STYLES:
            raise OpError(f"style must be one of {MARKUP_STYLES}, got {style!r}")
        out["style"] = style

    elif kind == "note":
        _require(op, "page")
        out["at"] = _point(_require(op, "at"))
        _require(op, "text")

    elif kind == "text_box":
        _require(op, "page")
        out["rect"] = _rect(_require(op, "rect"))
        _require(op, "text")
        out["size"] = float(op.get("size", 11))

    elif kind == "fill_field":
        _require(op, "field")
        _require(op, "value")

    elif kind == "place_signature":
        _require(op, "page")
        out["at"] = _point(_require(op, "at"))
        out["width"] = float(op.get("width", 180))
        out["signature"] = op.get("signature", "default")
        out["date"] = bool(op.get("date", False))

    if "page" in out:
        page = out["page"]
        if not (isinstance(page, int) and page >= 1):
            raise OpError(f"page must be a 1-based integer, got {page!r}")

    return out


def validate_all(ops: list) -> list[dict]:
    if not isinstance(ops, list):
        raise OpError("ops payload must be a JSON array of operation objects")
    return [validate(op) for op in ops]
