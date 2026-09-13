# macOS Preview vs omapdf — Research and Gap Analysis

**Date:** 2026-09-13  
**Scope:** PDF features only (Preview also edits images; that is out of scope).  
**Sources:** Apple Preview documentation and common Preview workflows; omapdf README, `docs/ops.md`, `docs/roadmap.md` (pbergin11/omapdf, AGPL-3.0-or-later).

---

## 1. What Preview is

Preview is the default macOS document viewer. For PDFs it is not Acrobat. It is a fast reader whose page model feels like a stack of paper: thumbnails on the left, markup on the page, Save writes the file.

The UX people miss on Linux is not “more annotation types.” It is:

1. Pages are first-class objects in the sidebar.
2. Add / remove / reorder / rotate / copy pages is instant and visual.
3. Pages copy between two open windows (Cmd+C / Cmd+V or drag).
4. Markup, sign, and redact live in the same window.
5. Save is one step. No “export as PDF” ritual.

omapdf already markets itself as “Preview.app for Linux.” The editor, agent loop, and annotation engine are ahead of Preview. Page surgery is not.

---

## 2. macOS Preview — PDF feature inventory

### 2.1 Viewing

| Feature | Notes |
|---|---|
| Thumbnail sidebar | View → Thumbnails (⌥⌘2). Resize sidebar. |
| Contact sheet | Grid of all pages. |
| Table of contents | If the PDF has an outline. |
| Highlights & Notes sidebar | Lists markup for jump-to. |
| Continuous scroll | Default multipage reading. |
| Single page / Two pages | Facing-page layout. |
| Zoom | Fit page, fit width, actual size, pinch, buttons. |
| Go to page | Menu and thumbnail click. |
| Full screen | Native macOS. |
| Search | Find text, highlight hits, cycle matches. |
| Text selection / copy | Select live text, copy to clipboard. |
| Print | System print dialog. |
| Share | macOS share sheet. |

### 2.2 Page handling (the Preview signature)

| Feature | How it works |
|---|---|
| Reorder pages | Drag thumbnails in the sidebar. |
| Delete pages | Select thumbnail(s) → Delete. Also Edit → Delete. |
| Multi-select | ⌘ click non-contiguous; ⇧ click range. |
| Rotate page(s) | ⌘L left, ⌘R right; toolbar rotate; two-finger rotate on trackpad. Applies to selection. |
| Copy pages | Select thumbnails → Cmd+C. |
| Paste pages | Cmd+V into the same or another Preview window. Inserts at drop / caret position in the thumbnail list. |
| Drag between windows | Open two PDFs, both in Thumbnails view, drag pages across. |
| Merge whole file | Drag a PDF from Finder into another PDF’s thumbnail sidebar. |
| Extract page | Drag a thumbnail to the desktop / Finder → new one-page PDF. |
| Insert blank page | Insert blank page into the page stack (via menu / insert). |
| Insert image as page | Drag an image into the thumbnail sidebar; it becomes a page. |
| Duplicate page | Copy + paste the same thumbnail. |

This is the gap that PDF Arranger covers on Linux, and that Preview does inside the reader.

### 2.3 Markup / annotation

From the Markup toolbar (View → Show Markup Toolbar):

| Tool | Behavior |
|---|---|
| Text selection | Select text to copy. |
| Rectangular selection | Region select on images / scans. |
| Sketch | Single-stroke shape; Preview can snap to a regular shape. |
| Draw | Freehand ink, pressure if available. |
| Shapes | Line, arrow, rectangle, oval, speech bubble, star, etc. |
| Highlight | Colored highlight, underline, strikethrough. Drag-to-place highlight shape also exists. |
| Text box | Free text overlay; font / size / color. |
| Notes | Sticky notes; listed in Highlights & Notes sidebar. |
| Loupe | Magnifier overlay. |
| Color / line / font | Style the current markup object. |
| Undo / Redo | Standard. Markup is editable until flattened by some export paths. |

Annotations are standard-ish PDF markup. They remain editable in Preview after save (until redaction is committed).

### 2.4 Forms and signing

| Feature | Behavior |
|---|---|
| Fill AcroForm fields | Click field, type. AutoFill since Sonoma for detected blank lines. |
| Checkboxes / radio | Native form widgets. |
| Visual signature | Create via trackpad, camera + paper, or Continuity (iPhone / iPad). Store multiple signatures. Place and resize. |
| Date next to signature | Common workflow; not a separate crypto signature. |
| No PAdES / certificate sign | Preview does not do cryptographic digital signatures. |

### 2.5 Redaction

| Feature | Behavior |
|---|---|
| Redact Selection tool | Drag over selectable text. Black bar. Editable until the document is closed / saved (Apple: “once you close the document, the redaction becomes permanent”). |
| Rectangle redact | Drag a box over images or non-text. |
| Warning | Apple tells users to duplicate first. Overlay shapes are **not** redaction. |

True content removal is the requirement. Preview’s implementation is “good enough for most civilians,” not FOIA-grade. omapdf’s own roadmap already calls for true removal plus loud warnings.

### 2.6 Security, export, images-in-PDF

| Feature | Behavior |
|---|---|
| Password on export / save | Restrict open and/or print/copy. |
| Quartz filters on export | Color/quality filters (macOS-specific). |
| Duplicate before edit | File → Duplicate. Autosave makes this important. |
| Crop page | Selection + crop. |
| Image conversion | Preview is also an image app (HEIC/JPEG/PNG/TIFF ↔ PDF). Out of PDF-parity scope except “image becomes a page.” |

### 2.7 Preview keyboard habits people expect

| Action | Preview |
|---|---|
| Thumbnails | ⌥⌘2 |
| Copy pages | ⌘C on selected thumbnails |
| Paste pages | ⌘V in another window |
| Delete pages | Delete |
| Rotate | ⌘L / ⌘R |
| Markup toolbar | toolbar button |
| Save | ⌘S (autosave on close is the Mac default) |

On Omarchy / Hyprland, Super is the compositor modifier. Page copy should be **Ctrl+C / Ctrl+V** in the app (Linux convention) with an optional Super binding in Hyprland — do not steal Super inside GTK.

---

## 3. omapdf — current feature inventory

omapdf is an agent-native Linux PDF tool: GTK4 editor, CLI, MCP server, Omarchy bar plugin. One JSON op engine (PyMuPDF) drives GUI, CLI, and agents.

License: AGPL-3.0-or-later.

### 3.1 Editor (shipped v0.2/v0.3)

| Area | What exists |
|---|---|
| View | Page view, fit-width that tracks viewport, zoom presets, Ctrl+scroll. |
| Thumbnails | Sidebar, toggle F9. **View-only navigation today** (no page surgery). |
| Nav | Up/Down, PgUp/PgDn, Home/End, Ctrl+G. |
| Search | Ctrl+F, cycle matches. |
| Tools | Select/drag, pen + tap-again color palette, highlighter, text, sticky notes, signature placement, green-check / red-cross stamps. |
| Ghost model | Pending ops are overlays. Nudge before save. Undo crosses the save boundary. |
| Agent ghosts | `omapdf edit doc.pdf --ops proposal.json` loads dry-run ops as draggable overlays. |
| Ask agent | ✦ opens Omarchy default agent with the file; editor watches disk and reloads. |
| Comments | Click saved annotation (ours or others’) to read it. |
| Share | Email attach, LocalSend, copy file/zip to clipboard, show in folder, flatten-copy-first. |

### 3.2 Op engine (shipped)

Documented in `docs/ops.md`. Pages are 1-based. Coordinates: PDF points, origin top-left, y down.

| Op | Purpose |
|---|---|
| `highlight` | highlight / underline / strikeout / squiggly via `match` or `rect` |
| `note` | sticky note at `at` |
| `text_box` | FreeText annotation |
| `fill_field` | AcroForm fill |
| `place_signature` | image signature + optional date |
| `ink` | freehand strokes |

Batch apply is atomic. Unknown ops fail the batch. `--dry-run` and `--json` exist everywhere.

### 3.3 CLI / MCP / Omarchy

CLI: `edit`, `read` (text + bboxes + fields + annots), `fields`, `annotate`, `note`, `sign`, `sig draw` / `sig add`, `snapshot --grid`, `apply --ops`, `flatten`, `open`.

MCP: `read_pdf`, `list_form_fields`, `apply_ops`, `highlight`, `add_note`, `fill_field`, `place_signature` (dry-run default), `list_signatures`, `flatten_pdf`.

Omarchy: `omapdf.bar` recent-PDFs pill; desktop file as default PDF handler.

### 3.4 Roadmap (already written by upstream)

**Next:** `sign --auto`, edit/delete saved annotations, comments summary page, stamp library, `omapdf diff`, toolbar overflow, selection → agent context.

**Later:** PAdES via pyHanko; **true redaction** with loud warnings.

**Not on the roadmap as first-class work:** thumbnail page surgery (add / delete / rotate / reorder / cross-window copy). That is the main Preview gap.

---

## 4. Gap analysis

Legend: **Have** = omapdf today. **Partial** = exists but weaker or different. **Missing** = Preview-class capability absent. **Beyond** = omapdf is ahead of Preview.

### 4.1 Where omapdf is ahead of Preview

| Capability | Why omapdf wins |
|---|---|
| Agent / MCP / CLI | Preview has none. |
| Structured `read` with bboxes | Agents can target text. |
| Dry-run + ghost confirm | Preview has no proposal workflow. |
| Undo across save | Preview autosave fights this. |
| Flatten as an explicit op | Clear “bake for other viewers” path. |
| Omarchy / Hyprland integration | Native on the target OS. |
| Planned PAdES | Preview never does crypto sign. |

Do not sacrifice these to imitate Preview.

### 4.2 Parity matrix (PDF only)

| Capability | Preview | omapdf | Gap |
|---|---|---|---|
| Thumbnail sidebar | Yes, interactive | Yes, F9, view-only | **Partial** |
| Contact sheet | Yes | No | Missing (low priority) |
| TOC / outline sidebar | Yes | No | Missing (medium) |
| Highlights & Notes list | Yes | Click-on-page only | Partial — roadmap “comments summary” |
| Continuous / single / two-page | Yes | Continuous-ish page view | Partial |
| Search | Yes | Yes | Have |
| Text copy | Yes | Via `read` / viewer select TBD | Partial — confirm GUI text select |
| **Reorder pages** | Drag thumbnails | No | **Missing — P0** |
| **Delete pages** | Select + Delete | No | **Missing — P0** |
| **Rotate pages** | ⌘L / ⌘R, multi-select | No | **Missing — P0** |
| **Copy/paste pages across windows** | Cmd+C/V + drag | No | **Missing — P0** |
| **Insert pages from another PDF** | Drag file or pages | No | **Missing — P0** |
| **Insert blank page** | Yes | No | **Missing — P0** |
| **Insert image as page** | Drag image to sidebar | No | **Missing — P1** |
| **Extract page to new file** | Drag thumbnail to Finder | Share/flatten only | **Missing — P1** |
| Multi-select pages | ⌘ / ⇧ | No | **Missing — P0** |
| Annotate (ink, text, note, highlight) | Yes | Yes | Have |
| Shapes (rect, arrow, oval) | Yes | Stamps + ink only | Partial — P2 |
| Sketch-to-shape | Yes | No | Missing — P3 |
| Loupe | Yes | No | Missing — P3 |
| Edit/delete existing annots | Yes | Roadmap | Partial — P1 (already planned) |
| Fill forms | Yes + AutoFill | `fill_field` + MCP | Partial — GUI form click-to-fill P1 |
| Visual signatures | Trackpad / camera / iOS | Draw window + PNG store | Have (input methods differ) |
| Crypto sign | No | Roadmap | Beyond Preview |
| **Redact text** | Redact Selection | Roadmap “later” | **Missing — P0** |
| **Redact region / image** | Box redact | No | **Missing — P0** |
| Password / permissions | Export options | No | Missing — P2 |
| Crop page | Yes | No | Missing — P2 |
| Print | Yes | Via system? | Confirm — P2 |
| Autosave | Yes | Explicit save + ghosts | Different by design — keep omapdf model |

### 4.3 Priority gaps (what “Preview parity” actually means)

**P0 — page handling + redaction**

Without these, omapdf is a great annotator, not Preview.

1. Page model in the sidebar: select, multi-select, reorder, delete, rotate.
2. Cross-document page clipboard + drag (two editor windows).
3. Insert blank page; insert pages from another PDF / from a file drop on the sidebar.
4. True redaction (text + rectangle), applied through the op engine, with duplicate-first warning.

**P1 — complete the Preview daily driver**

5. Extract selected pages to a new PDF / drag pages out to a file manager.
6. Insert image as a new page.
7. Edit / delete saved annotations (already on upstream roadmap).
8. Click-to-fill visible form fields in the editor.
9. Outline (TOC) sidebar.

**P2 — nice-to-have Preview extras**

10. Shapes (line, arrow, rect, oval).
11. Crop page.
12. Encrypt / permissions on save-as.
13. Two-page view; contact sheet.
14. Print action.

**P3 — skip or defer**

15. Continuity Camera signatures, Quartz filters, image-editor half of Preview, sketch-to-shape, loupe.

### 4.4 Design constraints (do not copy Preview blindly)

1. **Keep the op engine as the source of truth.** Every page mutation must be an op (`delete_pages`, `move_pages`, `rotate_pages`, `insert_pages`, `redact`) so CLI and agents get the same power as the GUI.
2. **Keep ghosts + explicit save.** Preview’s autosave is why Apple says “duplicate before redact.” omapdf should preview redactions as ghosts and commit on Save.
3. **Do not merge Xournal++ or PDF Arranger source.** Different engines (Poppler / pikepdf). Reimplement page ops on PyMuPDF, which omapdf and Censor already use.
4. **License.** omapdf is AGPL-3.0-or-later. Page-op ideas from PDF Arranger (GPL-3) and redaction ideas from Censor (GPL-3-or-later) are license-compatible if you copy code; prefer reimplementation + citation to keep provenance clean.
5. **Architecture.** User machine is aarch64 Omarchy. Stay Python + GTK4 + PyMuPDF. No x86-only deps.

### 4.5 Suggested success test (human)

A user can:

1. Open `a.pdf` and `b.pdf` in two omapdf windows.
2. Show thumbnails (F9).
3. Multi-select three pages in A, Ctrl+C, click between pages in B, Ctrl+V.
4. Select a sideways page, rotate 90°.
5. Select a junk page, press Delete.
6. Drop `scan.png` onto B’s sidebar → new page.
7. Highlight a clause, place a signature, draw a pen stroke.
8. Drag a redact box over a name; Save; reopen; `pdftotext` does not contain the name.
9. Undo the save if they made a mistake (ghost resurrection still works).

If that loop works, Preview parity for the requested scope is done.

---

## 5. References

- omapdf repository: https://github.com/pbergin11/omapdf
- omapdf ops: `docs/ops.md`
- omapdf roadmap: `docs/roadmap.md`
- Apple: View PDFs in Preview — https://support.apple.com/guide/preview/view-pdfs-and-images-prvw11470/mac
- Apple: Annotate a PDF in Preview — https://support.apple.com/guide/preview/annotate-a-pdf-prvw11580/mac
- Common Preview page workflows: thumbnails, Delete, drag between windows, Cmd+L / Cmd+R, Redact Selection
