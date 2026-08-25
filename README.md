# omapdf

**Preview.app for Linux — but your agent can drive it.**

omapdf is an agent-native PDF annotation and signing tool. Highlight, comment,
fill forms, and place your signature — from a CLI, from an AI agent over MCP,
or (soon) from a native Wayland GUI. Built for [Omarchy](https://omarchy.org),
useful on any Linux.

```bash
# A human signs a lease:
omapdf sig add ~/signature.png
omapdf sign lease.pdf --page 4 --at 120,540 --date -o lease-signed.pdf

# An agent does the whole thing:
#   "fill out this lease with my details, highlight anything unusual,
#    and get it ready for my signature"
```

## Why

The "someone emailed me a PDF, I need to highlight two things, sign it, and
send it back" workflow is macOS Preview's killer feature — and Linux has no
lightweight equivalent. Evince views, Xournal++ draws, Okular is a KDE
battleship. Nothing is fast, native, and *scriptable*.

And nobody anywhere has built a PDF tool that treats AI agents as first-class
users. omapdf's architecture makes that the whole point:

## One operations API, two clients

Every action — highlight, note, fill a field, stamp a signature — is a small
JSON operation. A document edit is a list of them. The CLI, the MCP server,
and the future GUI are all thin clients over the same engine:

```
        human                      agent
          │                          │
   ┌──────┴──────┐          ┌────────┴───────┐
   │  CLI / GUI  │          │  MCP server /  │
   │             │          │  Claude skill  │
   └──────┬──────┘          └────────┬───────┘
          │        ops (JSON)        │
          └───────────┬──────────────┘
              ┌───────┴───────┐
              │   op engine   │   validate → resolve → apply → report
              │   (PyMuPDF)   │
              └───────┬───────┘
                  document.pdf
```

Anything a human can do by hand, an agent can do by instruction — and every
applied op is echoed back with its resolved geometry, so either side can show
the other exactly what changed and where.

## Install

```bash
git clone https://github.com/omapdf/omapdf && cd omapdf
python -m venv .venv && .venv/bin/pip install -e '.[mcp]'
ln -s "$PWD/.venv/bin/omapdf" ~/.local/bin/omapdf
ln -s "$PWD/.venv/bin/omapdf-mcp" ~/.local/bin/omapdf-mcp
```

(Arch packaging in `packaging/PKGBUILD`; omarchy repo submission is on the
[roadmap](docs/roadmap.md).)

## Human usage

```bash
omapdf read contract.pdf                 # structured JSON: text, fields, boxes
omapdf read contract.pdf --text-only     # just the words
omapdf fields form.pdf                   # list fillable form fields

omapdf annotate doc.pdf --page 2 --match "termination clause"
omapdf note doc.pdf --page 2 --at 400,300 --text "negotiate this"
omapdf fill form.pdf --field tenant_name "Peter Bergin" --field rent "1800"

omapdf sig draw                          # draw your signature once (GTK window)
omapdf sig add ~/sig.png                 # …or import an image of it
omapdf sign doc.pdf --page 4 --at 120,540 --date
omapdf flatten doc.pdf -o final.pdf      # bake everything in for Acrobat folks
```

Signatures live in `~/.config/omapdf/signatures/`; `sig draw` again any time
to replace one. `omapdf open doc.pdf` opens your PDF viewer (`OMAPDF_VIEWER`
overrides), and `share/omapdf.desktop` lets you make omapdf the system's
default PDF handler:

```bash
cp share/omapdf.desktop ~/.local/share/applications/
xdg-mime default omapdf.desktop application/pdf
```

Everything accepts `-o out.pdf` (default is in-place), `--dry-run`, and
`--json`. Coordinates are PDF points with a top-left origin — the same
numbers `omapdf read` reports.

## Agent usage

Register the MCP server with Claude Code:

```bash
claude mcp add omapdf -- omapdf-mcp
```

Tools: `read_pdf`, `list_form_fields`, `apply_ops`, `highlight`, `add_note`,
`fill_field`, `place_signature`, `list_signatures`, `flatten_pdf`. A Claude
Code **skill** in [`skill/`](skill/) teaches the agent the full workflow —
read first, act with resolved coordinates, propose signature placements for
human confirmation.

**Safety posture:** `place_signature` is a dry run by default and returns the
placement rectangle for approval. Agents confirm with the human before the ink
lands. Automation-friendly, but consent-first.

## The editor

```bash
omapdf edit doc.pdf                      # GTK4 editor: select/drag, pen,
                                         # highlight, text, sign, ✓/✕ stamps
omapdf edit doc.pdf --ops proposal.json  # load agent proposals as draggable
                                         # ghosts — nudge, then Save
```

Everything you place is a *pending ghost* until Save — drag it, nudge with
arrow keys, delete it, undo/redo — then Save applies it through the same op
engine agents use. This is the agent-proposes / human-confirms loop working
today.

```bash
omapdf snapshot doc.pdf --page 1 --grid 50   # page as PNG with a labeled
                                             # coordinate grid — agents read
                                             # placement coordinates off it
```

## Omarchy integration

- **Top-bar widget** ([`shell-plugin/`](shell-plugin/)): a PDF pill in the
  Omarchy bar — click to pick a recent PDF and open it.
- Packaged like [omasnap](https://github.com/tobi/omasnap): a focused,
  single-purpose native tool, not a battleship.

## Status & roadmap

Early but real: the op engine, CLI, MCP server, and tests work today.
See [docs/roadmap.md](docs/roadmap.md) — headlines:

1. **v0.1 (now):** op engine, CLI, MCP server, signature store, bar widget
2. **v0.2:** form-field autodetect for signature lines, freehand ink ops,
   stamp library (dates, "APPROVED", initials)
3. **v0.3:** native Wayland GUI (Qt6 + poppler, omasnap-style) — the
   agent-proposes / human-confirms ghost-overlay flow
4. **v0.4:** cryptographic signing (PAdES) via pyHanko

## License

AGPL-3.0-or-later (matching our PyMuPDF dependency). See [LICENSE](LICENSE).
