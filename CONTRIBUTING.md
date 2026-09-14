# Contributing to omepreview

Contributions welcome — this project is young and the surface area is small
on purpose.

## Setup

```bash
git clone https://github.com/pbergin11/omepreview && cd omepreview
python -m venv --system-site-packages .venv   # system PyGObject for the editor
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest tests/ -q
```

Tests generate their own sample PDFs — no fixtures to download, and they run
in well under a second. Keep it that way.

## The one rule

**Everything goes through the op engine.** New capability = new op (schema in
`src/omepreview/ops.py`, applier in `src/omepreview/engine.py`, spec in `docs/ops.md`,
test in `tests/`). Then the CLI, MCP server, and GUI each get it as a thin
wrapper. If a feature can't be expressed as an op applied to a document,
question the feature.

Corollaries:

- Nothing agent-only, nothing human-only. Every new tool/command must be
  reachable from both sides.
- Errors are part of the API: they're read by agents, so make them state what
  went wrong *and* what to do next (see `fill_field`'s unknown-field error).
- Coordinates are PDF points, top-left origin, 1-based pages — everywhere,
  with no exceptions.
- Consequential actions (signing, flattening in place) default to
  dry-run/propose; confirmation is a caller decision, not an engine one.

## Style

Plain Python, standard library + PyMuPDF only in the core (`mcp` stays an
optional extra). Match the existing comment density — comments explain
constraints, not restate code.

## Bar widget / Omarchy bits

The shell plugin follows Omarchy's plugin conventions — see the
[Omarchy docs](https://omarchy.org) and keep `BarWidget.qml` minimal.

## License

AGPL-3.0-or-later. By contributing you agree to license your work the same way.
