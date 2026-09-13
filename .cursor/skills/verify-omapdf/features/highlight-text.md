# Highlight text

Highlight marks every exact occurrence of a phrase on a page as a standard PDF annotation (highlight, underline, strikeout, or squiggly) so a later `read` still sees it.

## Sub-features

- `highlight-dry-run` resolves match rects without writing the file.
- `highlight-write` writes a Highlight annotation to a copy (`-o`).
- `highlight-style` uses `--style underline` (or strikeout / squiggly).
- `highlight-miss` fails with an actionable error that says to run `omapdf read`.
- `highlight-second-view` re-reads the output and/or snapshots the page.

## How to get to it (user POV)

- Run `omapdf annotate <pdf> --page N --match "<exact phrase>"`.
- Add `--style underline` / `strikeout` / `squiggly` (default `highlight`).
- Add `--dry-run --json` to preview rects.
- Batch equivalent: `omapdf apply <pdf> --ops ops.json` with `{"op":"highlight","page":1,"match":"…"}`.
- Later / other surfaces: MCP `highlight`; GTK highlighter tool then **Save**.

## Driving it with control-omapdf

Preconditions:

- Isolated run from `control-omapdf launch`.
- `control-omapdf doctor` exits 0.
- Seed PDF is `$OMAPDF_VERIFY_DIR/work/lease.pdf`.
- Evidence dir is set and is not inside the run dir.

- **Baseline digest.** Hash the seed. Run `control-omapdf digest "$OMAPDF_VERIFY_DIR/work/lease.pdf"`. Record the `sha256:` line.
- **Dry-run.** Preview a match. Run `control-omapdf cli --capture highlight-text/dry-run.json -- annotate "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 1 --match "early termination clause" --dry-run --json`. Exit code `0`. Stdout `output` is `null`, `applied[0].applied` is `false`, `applied[0].rects` is a non-empty list.
- **Dry-run did not write.** Hash the seed again. Run `control-omapdf digest "$OMAPDF_VERIFY_DIR/work/lease.pdf"`. The digest matches the baseline.
- **Write highlight.** Annotate a copy. Run `control-omapdf cli --capture highlight-text/write.json -- annotate "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 1 --match "early termination clause" -o "$OMAPDF_VERIFY_DIR/work/highlighted.pdf" --json`. Exit code `0`. `applied[0].applied` is `true`, `output` is the copy path, `style` is `highlight`.
- **Second view (read).** Inspect annotations. Run `control-omapdf cli --capture highlight-text/read-after.json -- read "$OMAPDF_VERIFY_DIR/work/highlighted.pdf" --page 1`. Page 1 `annotations` includes `type` `Highlight`.
- **Second view (snapshot).** Render before and after. Run `control-omapdf cli -- snapshot "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 1 -o "$OMAPDF_VERIFY_EVIDENCE/highlight-text/before.png"` and `control-omapdf cli -- snapshot "$OMAPDF_VERIFY_DIR/work/highlighted.pdf" --page 1 -o "$OMAPDF_VERIFY_EVIDENCE/highlight-text/after.png"`. After PNG shows the yellow mark on `early termination clause`.
- **Miss.** Ask for absent text. Run `control-omapdf cli --capture highlight-text/miss.json -- annotate "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 1 --match "no such words" -o "$OMAPDF_VERIFY_DIR/work/should-not-exist.pdf" --json`. Exit code `1`. Stderr contains `not found` and `omapdf read`. The `-o` path is not created.
- **Proof.** Keep dry-run capture, both digests, write capture, read-after JSON, and both PNGs. Feature ID `highlight-text`.

## Gotchas

- `--match` is exact. Copy the string from `omapdf read`. PDF ligatures (`ﬁ`) make a typed `fi` miss.
- Default style is `highlight`, not underline. The CLI test uses `--style underline` — if you omit `--style`, assert `Highlight` not `Underline`.
- `--dry-run` still searches the page. Unchanged bytes are the write proof; `applied: false` alone is not enough.
- Annotate without `-o` overwrites the input. Verification always uses `-o`.
- GTK highlighter + Save is a different entry point. Do not mark it verified because the CLI path passed.
