# Place a signature

Place stamps a saved signature PNG onto a page at a top-left point. Signing is consequential: dry-run first, write only to a copy, never invent a signature.

## Sub-features

- `sign-store` lists the isolated `default` signature from this run's `XDG_CONFIG_HOME`.
- `sign-dry-run` resolves the placement rect without writing.
- `sign-write` writes the image into a copy (`-o`), optional `--date`.
- `sign-missing` fails with the list of saved names and `omapdf sig add` next step.

## How to get to it (user POV)

- Save a PNG: `omapdf sig add image.png --name default` (launch already did this in the isolated store).
- List: `omapdf sig list`.
- Place: `omapdf sign <pdf> --page N --at X,Y --width 150 --sig default -o signed.pdf`.
- Preview: same command with `--dry-run --json`.
- Later / other surfaces: MCP `place_signature` defaults to dry-run until `confirmed=true`; GTK signature tool then **Save**. `omapdf sig draw` is a GTK window — not this CLI recipe.

## Driving it with control-omapdf

Preconditions:

- Isolated run from `control-omapdf launch` (seeds `default` under the run's `XDG_CONFIG_HOME`).
- `control-omapdf doctor` exits 0.
- Seed PDF is `$OMAPDF_VERIFY_DIR/work/lease.pdf`. Page 2 has a `Signature:` label at text origin `(72, 300)` — place at `140,290` like the engine test.

- **List store.** Run `control-omapdf cli --capture place-signature/list.json -- sig list`. Exit code `0`. Stdout is `default`.
- **Baseline digest.** Run `control-omapdf digest "$OMAPDF_VERIFY_DIR/work/lease.pdf"`.
- **Dry-run.** Run `control-omapdf cli --capture place-signature/dry-run.json -- sign "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 2 --at 140,290 --width 150 --date --dry-run --json`. Exit code `0`. `output` is `null`, `applied[0].applied` is `false`, `applied[0].rect` width is 150, `date` is today's ISO date.
- **Dry-run did not write.** `control-omapdf digest` on the seed matches the baseline.
- **Write.** Run `control-omapdf cli --capture place-signature/write.json -- sign "$OMAPDF_VERIFY_DIR/work/lease.pdf" --page 2 --at 140,290 --width 150 --date -o "$OMAPDF_VERIFY_DIR/work/signed.pdf" --json`. Exit code `0`. `applied` is `true`. Output file exists.
- **Second view.** Run `control-omapdf cli -- snapshot "$OMAPDF_VERIFY_DIR/work/signed.pdf" --page 2 -o "$OMAPDF_VERIFY_EVIDENCE/place-signature/page2.png"`. PNG shows a stamp near the Signature line.
- **Proof.** Keep list, both digests, dry-run and write captures, page 2 PNG. Feature ID `place-signature`.

## Gotchas

- Without isolated `XDG_CONFIG_HOME`, `sig add` writes into the user's `~/.config/omapdf/signatures/`. Doctor must show isolation before this recipe.
- MCP `place_signature` is dry-run unless `confirmed=true`. CLI `--dry-run` is the matching posture. Do not skip the byte-digest check.
- `--at` is top-left of the image, PDF points, top-left origin.
- The image is page content, not an annotation — `read` annotations may not list it. Snapshot (or file existence + report rect) is the second view.
- Never run `sig draw` in this recipe (GTK). Never fabricate a signature PNG except the isolated seed from launch.
