# omapdf

- `Ownership-ID: Personal`. Load `ownership-profile-personal` when not already present.
- Agent-native PDF tool: GTK4 editor + CLI + MCP server over one PyMuPDF op engine.

## Commands

- Setup: `python -m venv --system-site-packages .venv` — plain venv hides system `gi`, breaks the editor.
- Install: `.venv/bin/pip install -e '.[dev]'`
- Test: `.venv/bin/python -m pytest tests/ -q` — must exit 0. Generates own PDFs, runs <1s.

## Navigate

- `src/omapdf/ops.py` schema, `src/omapdf/engine.py` sole write-path (`apply()`), `src/omapdf/cli.py`, `src/omapdf/mcp_server.py`.
- `src/omapdf/gui.py` editor — pending ghosts in `Editor.pending`, `Editor.to_ops()` on Save; rendering notes in `gui/README.md`.
- `docs/ops.md` stable op contract, `docs/roadmap.md` status, `docs/omapdf-preview-parity-spec.md` + `docs/omapdf-preview-gap-analysis.md` page-surgery plan.
- `tests/test_engine.py`, `skill/SKILL.md` agent playbook, `shell-plugin/omapdf.bar` bar widget, `packaging/PKGBUILD`.

## Bindings

- Linear: `omapdf` (AI Development). Live issue/branch: `index.md`.

## Rules

- New capability = new op: schema in `ops.py` + applier in `engine.py` + spec in `docs/ops.md` + test — keeps CLI, MCP, GUI in sync.
- Coordinates are PDF points, top-left origin, 1-based pages everywhere — `read` bboxes pass straight back as targets.
- Core stays stdlib + PyMuPDF; `mcp` remains an optional extra — keeps the Arch package lean.
- Errors state what failed and what to do next — agents read them (see `fill_field` unknown-field error).
- Consequential actions default to dry-run/propose; the caller confirms — never auto-commit sign/flatten/redact.
- GUI builds ops and Saves through the engine; no GUI-only writes — preserves human/agent parity.
- License is AGPL-3.0-or-later — match it; prefer reimplementation with citation over copying GPL code.

## Done here

- `pytest` green; new op ships all four parts; hand back files, test output, and gaps.
