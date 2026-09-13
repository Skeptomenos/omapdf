# omapdf verification map

This directory is the maintained source for verifying user-facing omapdf behavior. Read this index before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- Launch with `control-omapdf launch --evidence "$OMAPDF_VERIFY_EVIDENCE"`.
- Export `OMAPDF_VERIFY_DIR` from launch output. Never drive without it.
- Isolated `XDG_CONFIG_HOME` is inside the run dir (doctor checks this).
- Seed document is `$OMAPDF_VERIFY_DIR/work/lease.pdf` (2-page generated lease, not a user file).
- `control-omapdf doctor` exits 0.
- Put `control-omapdf` on `PATH` (`<repo>/.cursor/skills/verify-omapdf/scripts`).
- Never drive a GTK window or signature store this run did not create.

## Driving conventions

- Start every shippable recipe from the seeded lease unless the feature says otherwise.
- Treat every command as literal. Keep `--match` strings and flags unchanged.
- Run CLI actions through `control-omapdf cli -- …`.
- Always pass `-o` for writes. Use `--dry-run --json` before consequential edits.
- Restore the seed by recopying or re-launching after a mutation. Do not delete proof artifacts during cleanup.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final PNG.
- CLI proof includes the command, stdout, stderr, and exit code (`--capture`).
- Mutation proof includes a second view: `omapdf read` and/or `omapdf snapshot`.
- Dry-run proof includes unchanged `sha256` from `control-omapdf digest`.
- Record the feature ID and entry point with every artifact.
- Report an unreachable path with the attempted command and the unmet precondition. Do **not** report a skipped entry point as verified through a different path (CLI is not GTK; MCP is not CLI).
- Personal N26 PDFs and Engel-500 snapshots never go in git.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with control-omapdf` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required state, commands, and observable proof.

## Features

- [Read a document](./read-document.md) — structured JSON read, text-only, fields, snapshot grid.
- [Highlight text](./highlight-text.md) — annotate by exact match, dry-run vs write, miss error.
- [Fill a form field](./fill-form.md) — `fields` then `fill`, unknown-field error, flatten.
- [Place a signature](./place-signature.md) — isolated sig store, dry-run, then write with `-o`.
- [Engel-500 keep-only extract](./engel-500.md) — **later, not shippable.** Page-delete + true redact on personal statements. Ground truth: `SPEC.md` beside the fixtures. CLI + MCP + GTK required. Do not copy the PDFs into the repo.
