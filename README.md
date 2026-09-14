# omapreview

**Preview.app for Linux — but your agent can drive it.**

![omapreview — read, annotate, sign, or hand it to your agent](docs/assets/hero.png)

omapreview is an agent-native PDF tool: a fast GTK4 **editor** for reading,
annotating, and signing; a scriptable **CLI**; an **MCP server** for AI
agents; and an **Omarchy** integration that ties them all to the operating
system. One op engine underneath — anything a human can do by hand, an agent
can do by instruction, and vice versa.

```bash
omapreview edit lease.pdf                       # the editor
omapreview sign lease.pdf --page 4 --at 120,540 --date -o signed.pdf
# …or just tell your agent: "fill out this lease, highlight anything
#  unusual, and get it ready for my signature"
```

## Why

The "someone emailed me a PDF, I need to highlight two things, sign it, and
send it back" workflow is macOS Preview's killer feature — and Linux has no
lightweight equivalent. And nobody anywhere treats AI agents as first-class
PDF users. omapreview does both, with one architecture:

## One operations API, every client is thin

Every action — highlight, comment, fill a field, stamp a signature, draw ink
— is a small JSON operation. A document edit is a list of them. The editor,
the CLI, and the MCP server all funnel through the same engine:

```
     human                            agent
       │                                │
 ┌─────┴─────┐                 ┌────────┴────────┐
 │  editor   │                 │  MCP server /   │
 │  (GTK4)   │                 │  Claude skill   │
 └─────┬─────┘                 └────────┬────────┘
       │          ops (JSON)            │
       └──────────────┬─────────────────┘
              ┌───────┴───────┐
              │   op engine   │  validate → resolve → apply → report
              │   (PyMuPDF)   │
              └───────┬───────┘
                 document.pdf
```

Every applied op echoes back its resolved geometry, so either side can show
the other exactly what changed and where. Everything written is a
**standard PDF annotation** — Acrobat, Preview, and Evince users see your
notes and highlights as normal comments.

## The editor (`omapreview edit`)

A native GTK4 editor, Preview-fast, designed for Omarchy but plain-GTK
portable:

- **Preview-like page sidebar** (F9): thumbnails with multi-select, drag
  to reorder, delete/rotate shortcuts, context menu (extract, insert blank
  or file), drop PDFs/images onto the sidebar, Shift+drag to export pages
- **Two-window page copy**: Ctrl+C/V/X on selected thumbnails copies
  `application/x-omapdf-pages` (plus a PDF clipboard fallback) — paste
  between two editor windows like Preview
- **True redact** (R): text-snap or free-rectangle modes; translucent ghosts
  until Save; default writes `*_redacted.pdf` so the original stays. **Pen
  and ink are not redact** — only the `redact` op removes content from
  `get_text()` / `pdftotext`
- **Form fields**: click an empty AcroForm widget, type, Save → `fill_field`
  through the engine; select a saved annotation and Delete → `delete_annotation`
- **Tools** (hand-drawn vector icon set): select/drag, pen with a
  tap-again color palette, highlighter, text, sticky notes, signature
  placement, green-check and red-cross stamps, redact
- **Ghost model**: everything you place is a draggable, nudgeable pending
  item until Save bakes it through the op engine — and **undo crosses the
  save boundary**: Ctrl+Z after saving reverts the file and resurrects the
  saved items as editable ghosts
- **Reading comforts**: fit-width zoom that tracks the live viewport, zoom
  presets + Ctrl+scroll, full-document search (Ctrl+F) with match cycling,
  page navigation by Up/Down, PgUp/PgDn, Home/End, Ctrl+G go-to-page
- **Comments open on click**: click any saved annotation to read its text —
  including comments left by agents or by other people's PDF apps
- **Agent proposals as ghosts**: `omapreview edit doc.pdf --ops proposal.json`
  loads an agent's dry-run ops as selected, draggable overlays — nudge,
  then Save. Agent proposes, human confirms.
- **Ask your agent** (✦): type a question, it opens your OS default agent
  (`omarchy agent prompt`) with the document attached. The editor
  **watches the file** and reloads itself when the agent saves changes.
- **Share** (native, no fake share sheet): email attach, LocalSend, copy the
  file (or a zip of it) straight onto the clipboard, show in folder — with
  an optional flatten-copy-first toggle
- Save celebration included. You'll see.

## The CLI

```bash
omapreview read doc.pdf                  # structured JSON: text+bboxes, fields, annots
omapreview read doc.pdf --text-only      # just the words
omapreview fields form.pdf               # fillable fields with names and rects
omapreview snapshot doc.pdf --page 2 --grid 50   # page PNG with a labeled
                                     # coordinate grid — agents read placement
                                     # coordinates straight off the image

omapreview annotate doc.pdf --page 2 --match "termination clause"
omapreview note doc.pdf --page 2 --at 400,300 --text "negotiate this"
omapreview fill form.pdf --field tenant_name "Peter Bergin" --field rent "1800"
omapreview apply doc.pdf --ops edits.json        # atomic batch of ops

omapreview pages doc.pdf --list                  # page list (JSON)
omapreview pages doc.pdf --delete 2,4 -o out.pdf
omapreview pages doc.pdf --rotate 90 --pages 1 -o out.pdf
omapreview pages doc.pdf --move 5-6 --after 1 -o out.pdf
omapreview pages doc.pdf --insert other.pdf --after 2 -o out.pdf
omapreview pages doc.pdf --extract 2-3 -o excerpt.pdf

omapreview redact doc.pdf --page 1 --match "SSN" -o redacted.pdf
omapreview redact doc.pdf --page 1 --rect 72,400,300,430 -o redacted.pdf
omapreview delete-annotation doc.pdf --page 1 --index 0 -o out.pdf

omapreview sig draw                      # draw your signature once (GTK window)
omapreview sig add ~/sig.png --name work # …or import an image
omapreview sign doc.pdf --page 4 --at 120,540 --date -o signed.pdf
omapreview flatten doc.pdf -o final.pdf  # bake everything in for any viewer
omapreview open doc.pdf                  # opens the omapreview editor
```

Every edit command takes `-o` (default: in place), `--dry-run`, and
`--json` (each op returns its resolved geometry). Coordinates are PDF
points, origin top-left, 1-based pages — identical to what `read` reports.
The ops vocabulary is specified in [docs/ops.md](docs/ops.md).

## Agents

```bash
claude mcp add omapreview -- omapreview-mcp
```

MCP tools: `read_pdf`, `list_form_fields`, `apply_ops`, `highlight`,
`add_note`, `fill_field`, `place_signature` (dry-run by default —
confirm-before-ink), `list_signatures`, `list_pages`, `delete_pages`,
`rotate_pages`, `move_pages`, `insert_pages`, `extract_pages`, `redact`
and `delete_annotation` (dry-run by default), `flatten_pdf`.

The Claude Code **skill** in [`skill/`](skill/) is a full PDF-assistant
playbook: recipes for review-and-highlight, form filling, signing,
redlining, checklists, extraction with page citations — built around a
**precision ladder**: text anchors → grid snapshot (look at the page) →
dry-run → verify the written result visually → hand a draggable ghost to
the human when taste matters.

## Install

```bash
git clone https://github.com/pbergin11/omapreview && cd omapreview
python -m venv --system-site-packages .venv    # system gi for the GTK editor
.venv/bin/pip install -e '.[mcp]'
ln -s "$PWD/.venv/bin/omapdf" ~/.local/bin/omapreview
ln -s "$PWD/.venv/bin/omapreview-mcp" ~/.local/bin/omapreview-mcp
ln -s "$PWD/bin/omapreview-pick" ~/.local/bin/omapreview-pick
```

Requires Python ≥ 3.11, PyMuPDF, and (for the editor and `sig draw`)
PyGObject + GTK4 from your distro. Arch packaging in
[`packaging/PKGBUILD`](packaging/PKGBUILD).

Make omapreview your system PDF handler:

```bash
cp share/omapreview.desktop ~/.local/share/applications/
xdg-mime default omapreview.desktop application/pdf
```

## Omarchy integration

- **Top-bar widget** ([`shell-plugin/`](shell-plugin/)): a PDF pill —
  click for a recent-PDFs menu, pick one, it opens in the editor
  (`ln -s .../shell-plugin/omapdf.bar ~/.config/omarchy/plugins/omapdf.bar`,
  then `omarchy bar put omapdf.bar --section right`)
- **Ask-agent** uses `omarchy agent prompt`, so it launches whatever
  default agent the user picked (`omarchy default agent`), in Omarchy's
  native agent window; Voxtype dictation works in the ask box like any
  text field
- Packaged in the spirit of [omasnap](https://github.com/tobi/omasnap): a
  focused, single-purpose native tool

## Status & roadmap

**Preview parity shipped:** page sidebar surgery, two-window page clipboard,
true redaction, GUI form fill, and annotation delete — on CLI, MCP, and the
GTK editor. Human checklist: [docs/preview-parity.md](docs/preview-parity.md).

See [docs/roadmap.md](docs/roadmap.md) for what's next — headlines:
`sign --auto`, comments summary page, stamp library, cryptographic (PAdES)
signing via pyHanko. P2 backlog: shapes, crop, password on save-as.

## License

AGPL-3.0-or-later (matching our PyMuPDF dependency). See [LICENSE](LICENSE).
