# Roadmap

## Shipped

**v0.1 — the agent-native core**
- [x] Op engine: highlight/underline/strikeout/squiggly, notes, text boxes,
  form filling, signature placement with date stamp, freehand ink
- [x] Structured read: text blocks + bboxes, form fields, annotations
- [x] CLI with `--json`/`--dry-run` everywhere; atomic `apply` batches
- [x] MCP server (`omapdf-mcp`) with confirm-before-signing posture
- [x] Signature store + `sig draw` GTK drawing window
- [x] Claude Code skill: full PDF-assistant playbook with the precision
  ladder (anchors → grid snapshot → dry-run → visual verify → ghost handoff)
- [x] `snapshot --grid`: page PNG with a labeled ops-coordinate grid so
  agents can read placement coordinates visually
- [x] Omarchy bar widget (`omapdf.bar`) + recent-PDFs picker
- [x] Test suite over generated sample documents

**v0.2/v0.3 — the editor** (arrived early, in GTK4 rather than Qt)
- [x] `omapdf edit`: page view, hand-drawn vector icon toolbar, pill styling
- [x] Tools: select/drag, pen + tap-again color palette, highlighter, text,
  sticky notes, signature, check/cross stamps
- [x] Ghost model with undo/redo **across the save boundary** (a save is an
  undoable step; undoing it resurrects the items as editable ghosts)
- [x] `--ops` proposals load as draggable ghosts (agent proposes, human
  confirms)
- [x] Thumbnails sidebar, live fit-width, zoom presets + Ctrl+scroll,
  full-document search, complete page-navigation keys
- [x] Click-to-open saved comments (any PDF's annotations, not just ours)
- [x] Share menu: email attach, LocalSend, copy file / zip to clipboard,
  show in folder, flatten-copy-first toggle
- [x] Ask-your-agent (✦ → `omarchy agent prompt` with the file) + disk
  watcher that reloads the view when the agent saves changes
- [x] Default-PDF-handler desktop file (`omapdf open` → the editor)

## Next

- **`omapdf sign --auto`** — signature-line detection: "Signature:"/"Sign
  here" labels, ruled lines, signature-type fields → ranked placement
  proposals; agents and the editor both consume them as ghosts
- **Edit saved annotations** — select/move/delete existing annotations in
  the editor (a `delete_annotation` op first; move = delete + recreate)
- **Comments summary page** — append a final page listing every comment
  with its page number, for recipients with weak viewers or paper
- **Stamp library** — APPROVED / DRAFT / PAID / initials as a `stamp` op
  and an editor picker
- **`omapdf diff a.pdf b.pdf`** — agent-friendly version comparison
- **Toolbar overflow menu** — collapse tools into ⋯ at narrow widths
- **Selection → agent context** — "ask about this selection" sends the
  selected region's text along with the question

## Later

- **Cryptographic signing (v0.4)** — PAdES via pyHanko as an optional
  extra: certificates, visible + cryptographic signature in one op,
  `omapdf verify`. Kept clearly distinct from visual signing in the UX.
- **Redaction** — true content removal (not black boxes), with the
  loud warnings that feature demands

## Distribution

1. GitHub (repo URL placeholder: omapdf/omapdf), AUR package
   (`packaging/PKGBUILD`)
2. Omarchy plugin listing for the bar widget
3. Pitch to the omarchy package repo once polished (the omasnap path)
