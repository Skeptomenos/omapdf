# Read a document

Read lets a user inspect a PDF as structured JSON (text blocks with bboxes, form fields, annotations) or as plain text, and render a page PNG with an optional coordinate grid.

## Sub-features

- `read-json` returns page count, text blocks, fields, and annotations.
- `read-text` returns page text without layout (`--text-only`).
- `read-page` limits extraction to `--page N` (repeatable, 1-based).
- `read-fields` lists fillable fields with names, types, values, and rects.
- `read-snapshot` writes a PNG; `--grid 50` labels the ops coordinate system.

## How to get to it (user POV)

- Run `omapdf read <pdf>` in a terminal.
- Run `omapdf read <pdf> --text-only`.
- Run `omapdf fields <pdf>`.
- Run `omapdf snapshot <pdf> --page N --grid 50 -o page.png`.
- Later / other surfaces: MCP `read_pdf` / `list_form_fields`; GTK opens the same file visually but is not this recipe.

## Driving it with control-omapdf

Preconditions:

- Isolated run from `control-omapdf launch`.
- `control-omapdf doctor` exits 0.
- Seed PDF is `$OMAPDF_VERIFY_DIR/work/lease.pdf`.

- **Structured read.** Inspect the lease. Run `control-omapdf cli --capture read/json.json -- read "$OMAPDF_VERIFY_DIR/work/lease.pdf"`. Exit code `0`. Stdout JSON has `page_count` `2`, `has_form` true, page 1 text block containing `early termination clause`, page 2 field `tenant_name`.
- **Text-only.** Run `control-omapdf cli --capture read/text.json -- read "$OMAPDF_VERIFY_DIR/work/lease.pdf" --text-only`. Stdout pages include `RENTAL AGREEMENT` and `Tenant name:`.
- **One page.** Run `control-omapdf cli -- read "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 1`. JSON contains one page, `number` `1`.
- **Fields.** Run `control-omapdf cli --capture read/fields.json -- fields "$OMAPDF_VERIFY_DIR/work/lease.pdf"`. JSON array includes `name` `tenant_name`.
- **Snapshot.** Run `control-omapdf cli --capture read/snapshot.json -- snapshot "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 1 --grid 50 -o "$OMAPDF_VERIFY_EVIDENCE/read/page1-grid.png"`. Exit code `0`, PNG exists and is larger than 1 KB, JSON `page` is `1`.
- **Proof.** Keep the capture JSON and the PNG. The PNG must show the lease heading and labeled grid numbers (ops coordinates).

## Gotchas

- `read` writes JSON even without `--json`. `--text-only` without `--json` prints plain text instead.
- Pages are 1-based. `--page 0` is invalid.
- Snapshot `--grid` draws on a render copy; it is not a document edit. Still write the PNG into the evidence dir, not the git repo.
- Password-protected PDFs return `error: password-protected` — stop and ask for a decrypt.
- MCP `read_pdf` is a second entry point. Do not mark it verified because the CLI read passed.
