---
name: omapdf
description: Annotate, fill, and sign PDFs with omapdf. Use whenever the user asks to highlight/underline/comment on a PDF, fill a PDF form, sign a PDF, stamp a signature or date, flatten a PDF, or extract a PDF's text/fields for review. Triggers: "sign this pdf", "fill out this form", "highlight in the pdf", "annotate", "add a note to the pdf", "review this contract/lease", "flatten", "signature".
---

# omapdf — PDF annotation and signing

omapdf edits PDFs through a JSON op engine. Use the `omapdf` CLI (preferred in
terminal sessions) or the MCP tools if the `omapdf` MCP server is connected —
they are the same engine and can be mixed freely.

## Workflow: always read before you write

1. **Read the document first** to get real coordinates and field names:
   ```bash
   omapdf read doc.pdf              # pages, text blocks + bboxes, form fields
   omapdf read doc.pdf --text-only  # just the words (cheap first pass)
   omapdf fields form.pdf           # fillable fields with names and rects
   ```
   Coordinates are PDF points, origin **top-left** — bboxes from `read` can be
   passed straight back into ops.

2. **Act.** Single edits have dedicated commands; batch edits go through
   `apply` with an ops file (preferred for 2+ edits — it's atomic):
   ```bash
   omapdf annotate doc.pdf --page 2 --match "exact text from read" 
   omapdf note doc.pdf --page 2 --at 400,300 --text "Check this"
   omapdf fill form.pdf --field tenant_name "Jane Doe" --field rent "1800"
   omapdf apply doc.pdf --ops - <<'EOF'
   [{"op": "highlight", "page": 1, "match": "auto-renewal"},
    {"op": "note", "page": 1, "at": [450, 200], "text": "30-day notice required"}]
   EOF
   ```
   All edit commands accept `-o out.pdf` (default edits in place), `--dry-run`,
   and `--json` (returns each op with its resolved geometry).

3. **Verify** by re-reading or checking the `--json` report. `highlight
   --match` fails loudly if the text isn't found — re-read the page and match
   the document's actual wording (search is exact, not fuzzy).

## Signing — requires human confirmation

Placing a signature is consequential. Unless the user has already given an
explicit, specific instruction to sign (which page, roughly where):

1. Find the signature line: `omapdf read` and look for text like
   "Signature:" / "Sign here" — place the signature just above/right of it.
2. **Dry-run first** and show the user the placement:
   ```bash
   omapdf sign doc.pdf --page 4 --at 120,540 --width 180 --date --dry-run --json
   ```
3. On approval, run again without `--dry-run`. Offer `omapdf open doc.pdf`
   so they can eyeball the result.

Signature images are managed per-user:
```bash
omapdf sig list                      # saved signatures
omapdf sig add ~/sig.png --name work # PNG, transparent background best
```
If no signature is saved, run `omapdf sig draw` — it opens a drawing window
for the user to sign in (saved locally, reused thereafter; run it again to
replace). Never fabricate a signature image.

## Finishing touches

- `omapdf flatten doc.pdf -o final.pdf` — bakes annotations + form fields into
  page content. Use when the recipient needs a non-editable copy or uses a
  viewer that mishandles annotations. Keep the unflattened original.
- Annotations are real PDF annotations — Acrobat/Preview users see them as
  normal comments. Prefer them over text_box overlays for review feedback.

## Cautions

- Default is **in-place** editing: pass `-o` when the user would want the
  original kept (signing and flattening: recommend `-o` proactively).
- Password-protected PDFs are refused; tell the user to decrypt first.
- This tool does visual signing. For cryptographic (certificate) signatures,
  say it's on omapdf's roadmap — don't improvise one.
