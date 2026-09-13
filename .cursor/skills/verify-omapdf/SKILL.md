---
name: verify-omapdf
description: Drive omapdf's CLI the way a user or agent does — launch an isolated run, doctor it, apply real commands, and keep proof artifacts. Use when proving PDF read/annotate/fill/sign behavior, checking a regression, or running the later Engel-500 page-delete+redact validation (not shippable until those ops exist).
---

# Verify omapdf

omapdf is an agent-native PDF tool: GTK4 editor, CLI, and MCP server over one PyMuPDF op engine. This skill is for the **next agent**, read cold.

## Surfaces (interview)

**Primary surface for this skill: the `omapdf` CLI.** It is the documented human/agent path, `tests/test_engine.py::test_cli_end_to_end` already drives it via `python -m omapdf.cli`, and this environment can run it without a GUI session.

Also present, not the default drive path:

- **GTK4 editor** (`omapdf edit doc.pdf`, also `omapdf open`). Human Preview-like surface. Needs system `gi` (venv **must** be `python3 -m venv --system-site-packages .venv`) and a display. Save button accessible name is `Save`. Window title is `{filename} — omapdf`. Application id `org.omapdf.Editor`. `--ops proposal.json` loads as draggable ghosts; Save calls `engine.apply()`. There is no in-repo AT-SPI harness. `Editor.to_ops()` / `_load_proposals()` today only know `place_signature`, `text_box`, `highlight` (rect), `note`, `ink` — not page-delete or redact.
- **MCP** (`omapdf-mcp` stdio). Same engine. Tools today: `read_pdf`, `list_form_fields`, `apply_ops`, `highlight`, `add_note`, `fill_field`, `place_signature` (dry-run until `confirmed=true`), `list_signatures`, `flatten_pdf`. No `delete_pages` / `redact` tools yet.
- **Omarchy bar widget** (`shell-plugin/omapdf.bar`) — OS chrome, not the document tool.

Never treat a green `pytest` as proof of the editor or of Engel-500.

## Isolation

omapdf has **no server and no port**. Two CLI runs can coexist. Signatures live in `$XDG_CONFIG_HOME/omapdf/signatures/` (default `~/.config/omapdf/signatures/`).

Every verification run:

- Uses a disposable dir `OMAPDF_VERIFY_DIR=/tmp/omapdf-verify-$RUN_ID`.
- Sets `XDG_CONFIG_HOME=$OMAPDF_VERIFY_DIR/config` so signatures never touch the user's store.
- Writes outputs with `-o` into that dir. Never edit a user PDF in place.
- Refuses to drive if `run.json` is missing (no isolated launch).
- Does **not** start `omapdf edit` on a file the user already has open.

Evidence goes to `OMAPDF_VERIFY_EVIDENCE`, which **must not** be inside the run dir. Cleanup deletes the run dir only.

Personal bank statements for Engel-500 stay at `$OMAPDF_VERIFY_ENGEL500` (default in this project: `/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/internal/final-validations/engel-500/`). **Never copy those PDFs into the git repo. Never git-add `statement-2025-*.pdf`.**

## Launch

There is no long-lived app. Launch means: venv + isolated dirs + seeded `lease.pdf`.

```bash
export PATH="<repo>/.cursor/skills/verify-omapdf/scripts:$PATH"
export OMAPDF_VERIFY_EVIDENCE="<durable-evidence-dir>"   # required for a proof
export OMAPDF_REPO="<repo>"                              # optional if cwd is the repo
control-omapdf launch --evidence "$OMAPDF_VERIFY_EVIDENCE"
# ready line:
# omapdf-verify: ready
```

Then `eval` the printed `export OMAPDF_VERIFY_DIR=...` lines (or export them yourself).

Canonical install (from `AGENTS.md`):

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'
```

If `ensurepip` is missing (some cloud images), `control-omapdf launch` falls back to `venv --without-pip` plus `get-pip.py`. Still `--system-site-packages` so GTK `gi` stays visible. Plain venv without that flag hides system `gi` and breaks `omapdf edit`.

Ready: last launch line is `omapdf-verify: ready`, then `control-omapdf doctor` exits 0.

Teardown: `control-omapdf cleanup` (see Cleanup). After a failed iteration, run cleanup before launching again so `/tmp/omapdf-verify-*` dirs do not pile up.

## Doctor

Read-only. Run whenever anything looks off, and always before a proof.

```bash
control-omapdf doctor
# last line on success:
# omapdf-verify: doctor ok
```

It checks: `omapdf --version` (expect `omapdf 0.1.0` today), the isolated binary, run dir under `/tmp/omapdf-verify-*`, `XDG_CONFIG_HOME` inside the run dir, seeded `lease.pdf` (2 pages, `early termination clause`, field `tenant_name`), and that the evidence dir is **not** inside the run dir.

It also prints **later gaps**. Today `OP_TYPES` is `highlight, note, text_box, fill_field, place_signature, ink`. `delete_pages` and `redact` are missing — Engel-500 is **not shippable**. Doctor still exits 0 so current CLI features can be driven.

```bash
control-omapdf gaps    # exit 2 while those ops are missing
```

Do not drive an instance this run did not launch.

## Drive

Harness: `control-omapdf`. It prefixes the isolated `.venv/bin/omapdf` and injects `XDG_CONFIG_HOME`.

```bash
control-omapdf cli -- read "$OMAPDF_VERIFY_DIR/work/lease.pdf"
control-omapdf cli --capture highlight/annotate.json -- annotate "$OMAPDF_VERIFY_DIR/work/lease.pdf" \
  --page 1 --match "early termination clause" -o "$OMAPDF_VERIFY_DIR/work/highlighted.pdf" --json
```

`--capture` writes `{command, argv, exit_code, stdout, stderr, duration_ms}` as JSON under `OMAPDF_VERIFY_EVIDENCE` if the path is relative.

Literal flags from this repo (do not invent aliases):

| User action | Command |
| --- | --- |
| Structured read | `omapdf read doc.pdf` (JSON; `--text-only` for words; `--page N` repeatable) |
| Form fields | `omapdf fields form.pdf` |
| Highlight / underline / strikeout | `omapdf annotate doc.pdf --page N --match "exact text" --style highlight` |
| Sticky note | `omapdf note doc.pdf --page N --at X,Y --text "..."` |
| Fill field | `omapdf fill form.pdf --field NAME VALUE` (repeat `--field`) |
| Batch ops | `omapdf apply doc.pdf --ops ops.json` |
| Snapshot (PNG, optional grid) | `omapdf snapshot doc.pdf --page N --grid 50 -o page.png` |
| Sign | `omapdf sign doc.pdf --page N --at X,Y --sig default --date -o signed.pdf` |
| Flatten | `omapdf flatten doc.pdf -o final.pdf` |
| Dry-run any edit | add `--dry-run --json` |

Coordinates are PDF points, **top-left origin**, **1-based pages**. `--match` is exact page text from `read` (ligatures can break a match). Default edit is in-place; verification **always** uses `-o` on a copy.

MCP and GTK recipes live in the feature files. For current ops, MCP `apply_ops` / `highlight` is the same engine as the CLI. For Engel-500, both are **later**.

## Evidence

Proof standards:

- Exercise the **real CLI** (or, later, real MCP stdio / GTK Save). Do not call `engine.apply()` from Python as the proof.
- Capture the **action and the result**: command capture JSON **and** a second user-facing view (`omapdf read` annotations/fields, and/or `omapdf snapshot` PNG).
- For dry-run: `applied` is `false`, `output` is `null`, **and** `control-omapdf digest` on the source PDF is unchanged. Do not trust the flag name alone.
- Ink / black boxes are **not** redaction. Engel-500 later proof must show `omapdf read` no longer returns redacted payee strings.
- Do not put bank-statement PDFs or their snapshots into the git repo. Engel-500 evidence, when that proof eventually runs, stays in the private evidence dir.

`control-omapdf digest PATH` prints `sha256:<hex>  PATH`.

## Cleanup

```bash
control-omapdf cleanup
# omapdf-verify: cleaned run_dir=...
# omapdf-verify: evidence kept at ...
```

Kills only a GUI pid recorded in `run.json` (none on the default CLI path). Removes the run dir. **Never** deletes `OMAPDF_VERIFY_EVIDENCE`. After cleanup, confirm the evidence files still exist.

Do not `pkill omapdf`.

## Helpers

`scripts/control-omapdf` is executable:

```bash
control-omapdf launch --evidence "$OMAPDF_VERIFY_EVIDENCE"
control-omapdf doctor
control-omapdf cli --capture read.json -- read "$OMAPDF_VERIFY_DIR/work/lease.pdf"
control-omapdf digest "$OMAPDF_VERIFY_DIR/work/lease.pdf"
control-omapdf gaps
control-omapdf state
control-omapdf cleanup
```

## Feature map

Start at [`features/README.md`](features/README.md). Drive from the feature file, not from this overview.

Shippable today: read, highlight, fill, sign (dry-run first).

**Not shippable:** [`features/engel-500.md`](features/engel-500.md) — keep-only Torsten Engel `-500,00€` rows on personal N26 statements. Ground truth is **only** [`SPEC.md`](/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/internal/final-validations/engel-500/SPEC.md). Do not re-extract bboxes. Requires `delete_pages` + true `redact`, then CLI **and** MCP **and** GTK Save.

## Maintenance

When omapdf grows or a proof bitrots, use `/maintain-verification-skill` to keep this map honest.
