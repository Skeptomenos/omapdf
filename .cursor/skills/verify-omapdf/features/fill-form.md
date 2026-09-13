# Fill a form field

Fill writes a value into a named AcroForm field. The user lists fields first, fills by name, and can flatten so the value is page content instead of a widget.

## Sub-features

- `fill-list` lists field names, types, values, and rects.
- `fill-write` sets `tenant_name` on a copy.
- `fill-unknown` fails and lists the document's real field names.
- `fill-flatten` bakes fields into the page; `has_form` becomes false and the value is in text blocks.

## How to get to it (user POV)

- Run `omapdf fields <pdf>`.
- Run `omapdf fill <pdf> --field NAME VALUE` (repeat `--field`).
- Run `omapdf flatten <pdf> -o final.pdf`.
- Batch: `{"op":"fill_field","field":"tenant_name","value":"…"}` via `omapdf apply`.
- Later / other surfaces: MCP `list_form_fields` / `fill_field`; GTK has no separate form-fill tool today (typed `text_box` is not a widget fill).

## Driving it with control-omapdf

Preconditions:

- Isolated run from `control-omapdf launch`.
- `control-omapdf doctor` exits 0.
- Seed PDF is `$OMAPDF_VERIFY_DIR/work/lease.pdf` with empty `tenant_name`.

- **List fields.** Run `control-omapdf cli --capture fill-form/fields.json -- fields "$OMAPDF_VERIFY_DIR/work/lease.pdf"`. Exit code `0`. Array contains `tenant_name`.
- **Fill.** Run `control-omapdf cli --capture fill-form/write.json -- fill "$OMAPDF_VERIFY_DIR/work/lease.pdf" --field tenant_name "Peter Bergin" -o "$OMAPDF_VERIFY_DIR/work/filled.pdf" --json`. Exit code `0`. `applied[0].field` is `tenant_name`.
- **Second view.** Run `control-omapdf cli --capture fill-form/fields-after.json -- fields "$OMAPDF_VERIFY_DIR/work/filled.pdf"`. `tenant_name` `value` is `Peter Bergin`.
- **Unknown field.** Run `control-omapdf cli --capture fill-form/unknown.json -- fill "$OMAPDF_VERIFY_DIR/work/lease.pdf" --field nope x -o "$OMAPDF_VERIFY_DIR/work/nope.pdf" --json`. Exit code `1`. Stderr lists `tenant_name`.
- **Flatten.** Run `control-omapdf cli --capture fill-form/flatten.json -- flatten "$OMAPDF_VERIFY_DIR/work/filled.pdf" -o "$OMAPDF_VERIFY_DIR/work/flat.pdf" --json`. Then `control-omapdf cli -- read "$OMAPDF_VERIFY_DIR/work/flat.pdf"`. `has_form` is false and page 2 text blocks contain `Peter Bergin`.
- **Proof.** Keep fields-before, write capture, fields-after, unknown stderr, flatten read. Feature ID `fill-form`.

## Gotchas

- Checkbox values are `true`/`yes`/`on`/`1` (case-insensitive). The seed lease has a text field, not a checkbox.
- Flatten without `-o` overwrites. Always copy first.
- Flatten is irreversible in the output file. Keep `filled.pdf` unflattened.
- Filling via `text_box` on a non-form PDF is a different feature. Do not report it as `fill-form`.
