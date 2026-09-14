# PKGBUILD smoke — aarch64 / Omarchy

Slice 6 packaging notes. This cloud agent environment is **not** Arch Linux;
full `makepkg` was **not** run here. Use this as the Omarchy/aarch64 checklist.

## What was run here (any CPU)

| Step | Command | Result |
|------|---------|--------|
| Tests | `python3 -m pytest tests/ -q` | Must exit 0 before release |
| Wheel build | `python -m build --wheel --no-isolation` | Run from repo root after `pip install build hatchling` |
| CLI entry | `python3 -m omapreview.cli --version` | Confirms console scripts resolve |
| MCP import | `python3 -c "from omapreview.mcp_server import mcp"` | Optional extra |

## What needs Omarchy (or Arch aarch64)

Run on real hardware before publishing to AUR:

```bash
# From a clean Arch/aarch64 chroot or Omarchy machine
cd packaging
makepkg -f -si   # or -o for offline build
omapreview --version
omapreview-mcp --help 2>/dev/null || true   # needs python-mcp optdepend
omapreview edit /path/to/sample.pdf         # needs gtk4 + python-gobject
```

| Check | Notes |
|-------|--------|
| `depends` resolve | `python`, `python-pymupdf` on aarch64 |
| `optdepends` | `python-mcp`, Omarchy bar paths in `optdepends` comment |
| Desktop file | `share/omapreview.desktop` opens PDFs via `omapreview open` |
| Bar widget | `cp /usr/share/omapdf/shell-plugin/omapdf.bar ~/.config/omarchy/plugins/` |
| GTK editor | Page sidebar (F9), redact tool (R), form click-fill |

## PKGBUILD gaps to watch

- `arch=('any')` — pure Python; no native compile, but PyMuPDF wheel must exist for aarch64 on Arch.
- `pkgver` / `source` tarball — pin `sha256sums` on first tagged release (currently `SKIP`).
- Editor is not a hard `depends`; document `gtk4` + `python-gobject` for `omapreview edit` in README.

## Evidence

Slice 6 agent run: pytest log in
`/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-s6/pytest-output.txt`.
