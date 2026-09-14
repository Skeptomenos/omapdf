# The omapdf operations spec

A document edit is a JSON array of operation objects. This vocabulary is the
project's stable contract: the CLI, MCP server, and GUI are all clients of it,
and third-party tools are welcome to speak it directly (`omapdf apply doc.pdf
--ops ops.json`).

## CLI and MCP

Each op is available through `omapdf apply --ops file.json` and MCP
`apply_ops`. Convenience wrappers:

| Op | CLI | MCP |
|----|-----|-----|
| Page list | `omapdf pages FILE --list` | `list_pages` |
| Page surgery | `omapdf pages FILE --delete …` etc. | `delete_pages`, `rotate_pages`, `move_pages`, `insert_pages`, `extract_pages` |
| Redact | `omapdf redact FILE --page N --match …` or `--rect …` | `redact` (dry-run default) |
| Delete annot | `omapdf delete-annotation FILE --page N --index I` | `delete_annotation` (dry-run default) |
| Markup / forms | `annotate`, `note`, `fill`, `sign` | `highlight`, `add_note`, `fill_field`, `place_signature` |

Destructive MCP tools (`place_signature`, `delete_pages`, `redact`,
`delete_annotation`) default to dry-run; pass `confirm=true` (or
`confirmed=true` for signatures) after human approval.

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

### ink
```json
{"op": "ink", "page": 1, "strokes": [[[100, 200], [120, 220], [140, 200]]],
 "color": [0.75, 0.1, 0.1], "width": 2}
```
Freehand strokes as a real Ink annotation. `strokes` is a list of polylines
(each 2+ `[x, y]` points); `color` is `[r, g, b]` in 0..1 (default black);
`width` in points (default 2). Powers the editor's pen and its ✓/✕ stamps.
Report adds the bounding `rect`.

### rotate_pages
```json
{"op": "rotate_pages", "pages": [2, 3], "degrees": 90}
```
Rotates page objects (not a visual overlay). `degrees` ∈ {90, 180, 270, -90}.
Report: `{ "pages": [...], "degrees": 90 }`.

### delete_pages
```json
{"op": "delete_pages", "pages": [1, 4, 9]}
```
1-based page numbers. After apply, later pages compact. Deletes are applied
high-to-low. Refuses to delete every page unless `insert_pages` in the same
batch keeps the net count ≥ 1. Report: `{ "pages": [...] }`.

### move_pages
```json
{"op": "move_pages", "pages": [5, 6], "after": 1}
```
Reorder pages. `after`: 0 = beginning; N = after current page N. Report:
`{ "pages": [...], "after": 1 }`.

### insert_pages
```json
{"op": "insert_pages", "after": 2, "source": "other.pdf", "source_pages": [1, 2, 3]}
{"op": "insert_pages", "after": 0, "blank": {"count": 1, "width": 595, "height": 842}}
{"op": "insert_pages", "after": 1, "image": "scan.png"}
```
Exactly one of `source`, `blank`, or `image`. `source_pages` defaults to all
pages in the source PDF. Blank pages default to A4 (595×842 pt). Image pages
are sized to the previous page when `after` ≥ 1, otherwise to the image
pixels. Report includes `inserted` and which variant was used.

### extract_pages
```json
{"op": "extract_pages", "pages": [2, 3], "to": "excerpt.pdf"}
```
Writes selected pages to `to`. Does not modify the source document. Report:
`{ "pages": [...], "to": "excerpt.pdf" }`.

### redact
```json
{"op": "redact", "page": 1, "match": "Jane Doe"}
{"op": "redact", "page": 1, "rect": [72, 400, 300, 430], "fill": [0, 0, 0]}
```
Exactly one of `match` (every occurrence on the page) or `rect`. On apply,
PyMuPDF `add_redact_annot` + `apply_redactions()` removes matched text and
intersecting image samples, then fills the region opaque (default black).
`apply_now: false` adds redaction annotations as editable ghosts until a later
apply. Report adds `rects` and `verify: { "text_still_present": false }`; if
verify fails, the whole batch fails.

**Pen / ink is not redact.** Drawing a black ink stroke or rectangle overlay
covers content visually but leaves the underlying text in `get_text()` /
`pdftotext`. Only the `redact` op destroys content.

### delete_annotation
```json
{"op": "delete_annotation", "page": 1, "index": 0}
```
Removes one annotation on `page` by 0-based `index` (listed in `omapdf read`
under `annotations`). When deleting several on the same page in one batch,
indices are applied high-to-low so they stay valid. Report adds `type` and
`rect` of the removed annotation.

## Extending

New op = one schema clause in `ops.py` + one applier in `engine.py` + a spec
entry here + a test. Keep ops small and composable; a batch is the unit of
atomicity.

## Related docs

- [preview-parity.md](preview-parity.md) — manual acceptance checklist
- [roadmap.md](roadmap.md) — shipped vs next vs P2

Planned: `stamp` (library images: APPROVED, initials). See docs/roadmap.md.
