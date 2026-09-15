# PKGBUILD smoke — aarch64 / Omarchy

This cloud agent environment is **not** Arch Linux; full `makepkg` is run on
omarchy-air. GitHub is **omapreview** (a); the package and PATH command are
**omepreview** (e).

## Omarchy launcher (the path that works)

From a clone at `~/omepreview` on the PR/branch that contains this PKGBUILD:

```bash
cd ~/omepreview/packaging
makepkg -si
omepreview --version
omarchy-restart-walker
```

`makepkg -si` installs `/usr/bin/omepreview` and
`/usr/share/applications/omepreview.desktop`. Walker (Super+Space / Super+Alt+Space)
reads XDG desktop files; Elephant auto-detects new ones. If the name does not
appear immediately, `omarchy-restart-walker` restarts `elephant.service` and
`app-walker@autostart.service`.

**Do not** use `omarchy-refresh-applications` for this app. That script copies
Omarchy's bundled launchers into `~/.local/share/applications` (webapps, TUIs,
hidden entries) and is not how a pacman package registers.

Optional default PDF handler:

```bash
xdg-mime default omepreview.desktop application/pdf
```

## What was run here (any CPU)

| Step | Command | Result |
|------|---------|--------|
| Tests | `python3 -m pytest tests/ -q` | Must exit 0 before release |
| Wheel build | `python -m build --wheel --no-isolation` | Run from repo root after `pip install build hatchling` |
| CLI entry | `python3 -m omepreview.cli --version` | Confirms console scripts resolve |
| MCP import | `python3 -c "from omepreview.mcp_server import mcp"` | Optional extra |

## What needs Omarchy (or Arch aarch64)

```bash
cd packaging
makepkg -f -si
omepreview --version
omepreview-mcp --help 2>/dev/null || true   # needs python-mcp optdepend
omepreview edit /path/to/sample.pdf
```

| Check | Notes |
|-------|--------|
| `depends` resolve | `python`, `python-pymupdf` (aarch64 extra), `gtk4`, `python-gobject`, `python-cairo` |
| `optdepends` | `python-mcp`; Omarchy bar at `/usr/share/omepreview/shell-plugin/` |
| Desktop file | `omepreview open %f` — PATH binary, not `.venv` |
| Icon | `omepreview.svg` in hicolor scalable |
| Bar widget | `ln -s /usr/share/omepreview/shell-plugin/omapdf.bar ~/.config/omarchy/plugins/` |
| GTK editor | Page sidebar (F9), redact tool (R), form click-fill |

## PKGBUILD notes

- `arch=('any')` — pure Python; `python-pymupdf` must exist for the host arch (it does on Arch Linux ARM aarch64 extra).
- `source=()` — packages the parent of `packaging/` (this clone). There is no GitHub `v$pkgver` tarball; do not invent a release tag.
- `url` points at `Skeptomenos/omapreview`. A clone of `…/omepreview` (e) 404s.

## Evidence

Slice 6 agent run: pytest log in
`/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/media/preview-parity-s6/pytest-output.txt`.
