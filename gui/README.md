# The omepreview editor

The editor lives at [`src/omepreview/gui.py`](../src/omepreview/gui.py) and launches
with `omepreview edit doc.pdf` (also the target of `omepreview open` and the
`omepreview.desktop` handler). It is GTK4 + cairo + PyMuPDF — pure Python, no
compiled UI code. This directory holds its design notes.

## Design principles (all hold today)

1. **A client, not a fork.** The GUI builds the same JSON ops the CLI and
   MCP server produce and hands them to the same engine on Save. No
   GUI-only capabilities.
2. **Agent proposes, human confirms.** `--ops proposal.json` renders an
   agent's dry-run ops as selected, draggable ghost overlays — nudge with
   mouse or arrow keys, Save applies. The ✦ ask button closes the loop the
   other way: question → `omarchy agent prompt` → agent works → the disk
   watcher reloads the view when the file changes.
3. **Preview.app speed.** Open instantly, thumbnails, fit-width, search,
   sign, save. Nothing else fights for attention.

## Architecture notes

- **Ghost model**: pending items (`sig`, `text`, `note`, `highlight`,
  `ink`) live in `Editor.pending`, draw over the rendered page, and
  convert via `Editor.to_ops()` on Save. Signatures are SVG; the Sign
  tool lists saved ones for drag-and-drop onto the page. Selection =
  identity in that list.
- **Undo across saves**: the undo stack holds two entry kinds — pending
  snapshots and *save boundaries* (pre/post file bytes + the pending list
  that was saved). Undoing a save writes the old bytes back and restores
  the items as ghosts.
- **Rendering**: current page rasterized by PyMuPDF at the fit/zoom scale
  into a cairo surface; ghosts and search-match overlays draw above it in
  page coordinates (ctx scaled by zoom).
- **Icons**: hand-drawn cairo painters (`paint_*`) in one stroke language,
  colored by the widget's foreground (theme-proof); the pen icon draws in
  the current ink color and doubles as the color indicator.
- **File watcher**: a `Gio.FileMonitor` reloads doc + thumbnails on
  external changes, guarded against omapdf's own writes (save/undo/redo).
- **Comments**: clicking near a saved annotation (select tool) pops its
  content — values are copied out of the PyMuPDF annot objects inside the
  iteration loop (they can go stale), and the popover opens via
  `GLib.idle_add` so the triggering click can't dismiss it.

## Known limits / next steps

- Saved annotations can be read but not yet moved or deleted from the GUI
  (needs a `delete_annotation` op — see the roadmap).
- Single-page view (no continuous scroll across pages); Up/Down and the
  sidebar make this cheap, but continuous mode may come later.
- At very narrow window widths the toolbar needs an overflow ⋯ menu.
