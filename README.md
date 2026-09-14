# omepreview

**A Preview-class PDF studio for Omarchy and plain GTK Linux.**

omepreview is a fast GTK4 editor for reading, marking up, and signing PDFs — with Preview-style page surgery, true redaction, and trackpad signatures. One calm editorial surface for humans; one JSON op engine underneath for agents.

<p align="center">
  <img src="docs/screenshots/gtk-light-fit-editorial.png" alt="omepreview — light theme, page fit" width="720" />
</p>

<p align="center">
  <img src="docs/screenshots/gtk-dark-fit-editorial.png" alt="omepreview — dark theme" width="360" />
  &nbsp;
  <img src="docs/screenshots/gtk-light-zoom-into-page.png" alt="omepreview — zoomed page" width="360" />
</p>

<p align="center">
  <img src="docs/screenshots/gtk-signature-draw.png" alt="omepreview — trackpad signature recorder" width="420" />
  &nbsp;
  <img src="docs/screenshots/gtk-light-save-ghost.png" alt="omepreview — ghost Save on the overlay rail" width="200" />
</p>

---

## What you get

| Surface | Role |
|--------|------|
| **GTK editor** | Paper-on-desk chrome, overlay tool rail, thumbnails, pinch zoom |
| **CLI** | `read`, `edit`, `sign`, `pages`, `apply` — scriptable and agent-friendly |
| **MCP** | `omepreview-mcp` optional extra; same ops as the CLI |
| **Signatures** | Preview-style trackpad recorder (`omepreview sig draw`) + placement on the page |

**Page knife** — insert, delete, rotate, extract, reorder via sidebar or ops.  
**True redact** — content removal, not just black rectangles.  
**Editorial rail** — transparent glyphs at 62% ink; ghost Save until you have pending work.

Forked from [omapdf](https://github.com/pbergin11/omapdf). omepreview is its own product.

## Install

```bash
git clone https://github.com/Skeptomenos/omepreview.git
cd omepreview
python -m venv --system-site-packages .venv   # keeps system GTK bindings
.venv/bin/pip install -e '.[dev]'
```

Arch: [`packaging/PKGBUILD`](packaging/PKGBUILD) (`pkgver=0.0.1`).

## Quick start

```bash
omepreview edit document.pdf
omepreview read document.pdf --json
omepreview sig draw                   # Space to record, finger glide, Enter saves SVG
omepreview sign document.pdf --page 2 --at 120,540 -o signed.pdf
omepreview --version                  # omepreview 0.0.1
```

Desktop handler: `share/omepreview.desktop` · Application ID: `org.omepreview.Editor`

## For agents

Every edit is a list of JSON ops. See [`docs/ops.md`](docs/ops.md).

```bash
omepreview apply --ops edits.json -o out.pdf
omepreview-mcp
```

Trackpad signing notes: [`docs/signature-trackpad.md`](docs/signature-trackpad.md)

## License

[AGPL-3.0-or-later](LICENSE)
