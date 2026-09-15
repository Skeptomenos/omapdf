---
name: omepreview
description: Do anything with a PDF that a person would ask an assistant to do — review and highlight what matters, mark up or annotate anything, fill forms, sign, initial, stamp, redline, cross out, flatten, extract or summarize with page citations. Triggers: any request involving a PDF — "sign this", "fill this out", "highlight everything I need to know", "mark up", "go through this document", "review this contract/lease/agreement", "annotate", "add a note", "cross out", "check off", "redline", "flatten", "what does this PDF say", "signature".
---

# omepreview — the PDF assistant playbook

omepreview edits PDFs through a JSON op engine (`omepreview`` CLI; the `omepreview`` MCP
server exposes the same engine). Treat ANY request a person would make about
a paper document as executable: if a human with a pen and a highlighter could
do it, you can do it — and you can also *look at the page* to work precisely.

Ops: `highlight` (styles: highlight/underline/strikeout/squiggly), `note`
(sticky comment), `text_box` (visible text), `fill_field`, `place_signature`,
`ink` (freehand strokes / marks). Coordinates are PDF points, origin
top-left; pages are 1-based; bboxes from `read` feed straight back into ops.

## The precision ladder

The signature flow taught the pattern: **anchor → look → dry-run → verify →
(if aesthetic/consequential) hand a ghost to the human.** Climb only as high
as the task needs:

1. **Text anchors.** `omepreview read doc.pdf` gives every text block + bbox and
   every form field + rect. `highlight --match` needs no coordinates at all.
   Compute positions *relative to* known bboxes (e.g. signature goes just
   above the "SIGNATURE" label's bbox; a check goes at the checkbox rect).
2. **Use your eyes.** When text blocks don't pin it down (image-heavy pages,
   empty regions, "next to the logo", column layouts):
   `omepreview snapshot doc.pdf --page N --grid 50` → Read the PNG → the labeled
   grid IS the ops coordinate system. Pick numbers off it.
3. **Dry-run.** Every edit command takes `--dry-run --json` and returns
   resolved geometry without writing. Sanity-check rects fit the page and
   don't cover content you must keep readable.
4. **Verify after writing.** For anything nontrivial, write to a copy
   (`-o out.pdf`), then `omepreview snapshot out.pdf --page N` (no grid) and
   *look at the result*. Wrong spot, overlapping text, too big? Fix the op
   and re-apply to a fresh copy from the original. Never ship what you
   haven't seen.
5. **Ghost handoff.** For placements where taste matters (signatures, stamps
   on a designed page) or when the user should have final say: write the
   proposed ops to JSON and `setsid -f omepreview edit doc.pdf --ops proposal.json`
   — they load as selected, draggable overlays; the user nudges and Saves.

## Task recipes

**"Go through this and highlight everything I need to know"** — the flagship.
1. `omepreview read doc.pdf --text-only` — read the WHOLE document, every page.
2. Identify what a diligent professional would flag: money (amounts, fees,
   penalties), dates and deadlines, obligations ("shall", "must", "agrees
   to"), auto-renewals, termination/cancellation terms, liability and
   indemnity, anything unusual or one-sided, anything contradicting what the
   user told you.
3. One atomic batch: `highlight` each key phrase (`--match` uses exact text —
   copy it verbatim from the read); add a `note` beside each non-obvious one
   saying WHY it matters.
4. Deliver a page-anchored summary in chat: "p2: 4% late fee after 5 days
   (highlighted); p5: auto-renews unless cancelled 60 days out (highlighted +
   note)…". The markup and the summary are one deliverable.

**"Mark up / annotate all X"** — `highlight --match` marks every occurrence
on a page; loop the pages where `read` shows the term. Verify the count you
report matches the rects returned.

**Fill a form** — `omepreview fields form.pdf` for names/types/rects. Fill every
field you have facts for in one `apply` batch. Never invent values: leave
unknown fields empty and list them for the user. No AcroForm fields? Use
`text_box` placed by the ladder (label bboxes → grid snapshot).

**Sign / initial** — signature lines come from field rects (`signature`
type), "SIGNATURE"/"Sign here"/"X___" labels, or the grid snapshot. Dry-run,
then apply, then verify with a snapshot. "Initial every page": a saved
`initials` signature (`omepreview sig add ... --name initials`) placed at a
consistent corner on every page in one batch. Never place a signature the
user hasn't asked for; offer the ghost handoff when placement is aesthetic.

**Redline / propose edits** — `strikeout` the old wording (`--match`), put
replacement text nearby via `text_box`, and a `note` with the rationale.
Recipients see standard annotations in any viewer.

**Check off / cross out lists** — `ink` with a check
(`[[[x,y+7],[x+4.5,y+12],[x+14,y]]]`, green `[0.18,0.62,0.31]`) or cross
(two diagonal strokes, red) at each checkbox rect from `read`.

**Stamp / label** — `text_box` for "APPROVED", "DRAFT", "PAID", dates;
red/large for stamps. Position by the ladder.

**Extract / summarize / answer questions** — `read --text-only` and answer
with page citations. You are also the fastest way to *find* things: quote
exactly, cite pages.

**Compare two versions** — `read --text-only` both, diff the text yourself,
then mark the changes on the newer file (highlight additions, strikeout
removals) and summarize.

**Send it somewhere** — the agent is the share sheet. When connected tools
allow (email, Slack, etc.), "sign it and send it to X" is one flow: finalize
(usually `flatten -o final.pdf`), attach, send — confirming recipient and
message before sending, and reporting exactly what was sent. Humans also have
a Share menu in `omepreview edit` (email attach, LocalSend, copy-file,
show-in-folder).

## Discipline

- **Read the whole document before acting.** Every recipe starts with read.
- **Batch edits into one `apply`** — it's atomic; a bad op aborts the batch
  before anything is written.
- **Exact match gotcha:** PDF text may use ligatures (ﬁ, ﬂ) — if a match
  fails, try a shorter distinctive phrase avoiding fi/fl words; the error is
  actionable and `read` shows the true text.
- **Keep originals.** Use `-o` for signing, flattening, and anything the
  user may want to redo; edit in place only for additive annotation the user
  asked for on that file.
- **Redact means destroy.** Region redact removes page text in the rectangle
  **and** intersecting sticky notes/replies, FreeText, file attachments, and
  form values. Word-snap verify is glyph-coverage, not `get_textbox` clip —
  a neighbor that only grazes the box is not leftover; a glyph still inside
  is named in the error. Unsupported intersecting annot types fail closed —
  do not report a successful redact while a payload remains. Ink/black boxes
  are not redact.
- **Finish for sending:** offer `omepreview flatten out.pdf -o final.pdf` when
  the copy is going to someone else; keep the unflattened version. Flatten
  refuses if the file still has pending PDF redaction annotations — apply a
  reviewed `redact` first; do not treat flatten as apply-redactions.
- Password-protected PDFs are refused — ask the user to decrypt.
- No signature saved? `omepreview sig draw` opens the trackpad recorder
  (Space / finger-on-pad absolute mapping / Enter → SVG). Never fabricate a signature, never
  sign unbidden, never invent form data.
- Visual signing only; cryptographic (certificate) signing is on the
  roadmap — say so, don't improvise it.
- `omepreview open doc.pdf` opens the omepreview editor for the user (detach GUI
  launches: `setsid -f`).
