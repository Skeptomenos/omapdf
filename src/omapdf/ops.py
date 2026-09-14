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
SHAPE_TYPES = ("line", "arrow", "rect", "oval")

OP_TYPES = (
    "highlight",
    "note",
    "text_box",
    "fill_field",
    "place_signature",
    "ink",
    "rotate_pages",
    "delete_pages",
    "move_pages",
    "insert_pages",
    "extract_pages",
    "redact",
    "delete_annotation",
    "shape",
)

_ROTATE_DEGREES = (90, 180, 270, -90)


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


def _page_list(value, key: str = "pages") -> list[int]:
    if not (isinstance(value, list) and value):
        raise OpError(f"{key} must be a non-empty list of 1-based page numbers")
    out = []
    for p in value:
        if not (isinstance(p, int) and p >= 1):
            raise OpError(f"{key} entries must be 1-based integers, got {p!r}")
        out.append(p)
    return out


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

    elif kind == "ink":
        _require(op, "page")
        strokes = _require(op, "strokes")
        if not (isinstance(strokes, list) and strokes and all(
            isinstance(s, list) and len(s) >= 2 for s in strokes
        )):
            raise OpError("ink needs strokes: [[[x,y],...], ...], each with 2+ points")
        out["strokes"] = [[_point(p) for p in s] for s in strokes]
        color = op.get("color", [0, 0, 0])
        if not (isinstance(color, (list, tuple)) and len(color) == 3):
            raise OpError(f"color must be [r, g, b] in 0..1, got {color!r}")
        out["color"] = [float(c) for c in color]
        out["width"] = float(op.get("width", 2))

    elif kind == "place_signature":
        _require(op, "page")
        out["at"] = _point(_require(op, "at"))
        out["width"] = float(op.get("width", 180))
        out["signature"] = op.get("signature", "default")
        out["date"] = bool(op.get("date", False))

    elif kind == "rotate_pages":
        out["pages"] = _page_list(_require(op, "pages"))
        degrees = _require(op, "degrees")
        if degrees not in _ROTATE_DEGREES:
            raise OpError(f"degrees must be one of {_ROTATE_DEGREES}, got {degrees!r}")
        out["degrees"] = degrees

    elif kind == "delete_pages":
        out["pages"] = _page_list(_require(op, "pages"))

    elif kind == "move_pages":
        out["pages"] = _page_list(_require(op, "pages"))
        after = _require(op, "after")
        if not (isinstance(after, int) and after >= 0):
            raise OpError(f"after must be a non-negative integer (0 = beginning), got {after!r}")
        out["after"] = after

    elif kind == "insert_pages":
        after = _require(op, "after")
        if not (isinstance(after, int) and after >= 0):
            raise OpError(f"after must be a non-negative integer (0 = beginning), got {after!r}")
        out["after"] = after
        has_source = "source" in op
        has_blank = "blank" in op
        has_image = "image" in op
        variants = sum((has_source, has_blank, has_image))
        if variants != 1:
            raise OpError("insert_pages needs exactly one of 'source', 'blank', or 'image'")
        if has_source:
            out["source"] = str(_require(op, "source"))
            if "source_pages" in op:
                out["source_pages"] = _page_list(op["source_pages"], "source_pages")
        if has_blank:
            blank = _require(op, "blank")
            if not isinstance(blank, dict):
                raise OpError("blank must be an object with count, width, height")
            count = blank.get("count", 1)
            if not (isinstance(count, int) and count >= 1):
                raise OpError(f"blank.count must be a positive integer, got {count!r}")
            out["blank"] = {
                "count": count,
                "width": float(blank.get("width", 595)),
                "height": float(blank.get("height", 842)),
            }
        if has_image:
            out["image"] = str(_require(op, "image"))

    elif kind == "extract_pages":
        out["pages"] = _page_list(_require(op, "pages"))
        out["to"] = str(_require(op, "to"))

    elif kind == "redact":
        _require(op, "page")
        if ("match" in op) == ("rect" in op):
            raise OpError("redact needs exactly one of 'match' or 'rect'")
        if "rect" in op:
            out["rect"] = _rect(op["rect"])
        fill = op.get("fill", [0, 0, 0])
        if not (isinstance(fill, (list, tuple)) and len(fill) == 3):
            raise OpError(f"fill must be [r, g, b] in 0..1, got {fill!r}")
        out["fill"] = [float(c) for c in fill]
        if "apply_now" in op:
            out["apply_now"] = bool(op["apply_now"])

    elif kind == "delete_annotation":
        _require(op, "page")
        index = _require(op, "index")
        if not (isinstance(index, int) and index >= 0):
            raise OpError(f"index must be a non-negative integer, got {index!r}")
        out["index"] = index

    elif kind == "shape":
        _require(op, "page")
        shape = _require(op, "shape")
        if shape not in SHAPE_TYPES:
            raise OpError(
                f"unknown shape {shape!r}; valid shapes: {', '.join(SHAPE_TYPES)}"
            )
        out["shape"] = shape
        if shape in ("line", "arrow"):
            out["from"] = _point(_require(op, "from"))
            out["to"] = _point(_require(op, "to"))
        else:
            out["rect"] = _rect(_require(op, "rect"))
        color = op.get("color", [0, 0, 0])
        if not (isinstance(color, (list, tuple)) and len(color) == 3):
            raise OpError(f"color must be [r, g, b] in 0..1, got {color!r}")
        out["color"] = [float(c) for c in color]
        out["width"] = float(op.get("width", 2))

    if "page" in out:
        page = out["page"]
        if not (isinstance(page, int) and page >= 1):
            raise OpError(f"page must be a 1-based integer, got {page!r}")

    return out


def validate_all(ops: list) -> list[dict]:
    if not isinstance(ops, list):
        raise OpError("ops payload must be a JSON array of operation objects")
    return [validate(op) for op in ops]
