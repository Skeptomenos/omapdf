# The omapdf operations spec

A document edit is a JSON array of operation objects. This vocabulary is the
project's stable contract: the CLI, MCP server, and GUI are all clients of it,
and third-party tools are welcome to speak it directly (`omapdf apply doc.pdf
--ops ops.json`).

## Conventions

- **Pages are 1-based** everywhere a human or agent sees them.
- **Coordinates are PDF points** (1/72"), origin at the **top-left** of the
  page, y growing downward — identical to what `omapdf read` reports, so a
  bbox from a read can be passed straight back as a target.
- Every applied op is echoed back in the report with its resolved geometry
  (`rects`, `rect`, `page`) and `"applied": true|false` (false = dry run).
- Validation is strict: unknown ops, missing keys, and unmatched text fail
  the whole batch before anything is written.

## Operations

### highlight
```json
{"op": "highlight", "page": 1, "match": "early termination clause"}
{"op": "highlight", "page": 1, "rect": [72, 130, 400, 148], "style": "underline"}
```
Exactly one of `match` (exact text search; every occurrence on the page is
marked) or `rect`. `style`: `highlight` (default) | `underline` | `strikeout`
| `squiggly`. Report adds `rects`.

### note
```json
{"op": "note", "page": 2, "at": [450, 200], "text": "30-day notice required"}
```
A sticky-note (Text) annotation — renders as a comment icon in any viewer.

### text_box
```json
{"op": "text_box", "page": 2, "rect": [100, 300, 300, 330], "text": "N/A", "size": 11}
```
A FreeText annotation: visible text drawn on the page (e.g., writing into a
non-form document). `size` defaults to 11pt.

### fill_field
```json
{"op": "fill_field", "field": "tenant_name", "value": "Jane Doe"}
```
Fills an AcroForm field by name (find names with `omapdf fields`). Checkbox
fields accept `true/yes/on/1` (case-insensitive). Unknown names fail with the
document's actual field list in the error. Report adds `page`.

### place_signature
```json
{"op": "place_signature", "page": 4, "at": [120, 540], "width": 180,
 "signature": "default", "date": true}
```
Stamps a saved signature PNG with its top-left corner at `at`, scaled to
`width` points (height keeps the image's aspect ratio). `signature` names an
image saved via `omapdf sig add` (default: `"default"`). `date: true` writes
today's ISO date below. Report adds `rect` (and `date`).

Note: the image is inserted into page content, not as an annotation — it
survives every viewer and doesn't need flattening.

## Extending

New op = one schema clause in `ops.py` + one applier in `engine.py` + a spec
entry here + a test. Keep ops small and composable; a batch is the unit of
atomicity.

Planned: `ink` (freehand strokes), `stamp` (library images: APPROVED, initials),
`redact`. See docs/roadmap.md.
