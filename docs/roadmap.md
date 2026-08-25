# Roadmap

## v0.1 — the agent-native core (now)

- [x] Op engine: highlight/underline/strikeout, notes, text boxes, form
  filling, signature placement with date stamp
- [x] Structured read: text blocks + bboxes, form fields, annotations
- [x] CLI with `--json`/`--dry-run` everywhere
- [x] MCP server (`omapdf-mcp`) with confirm-before-signing posture
- [x] Signature store (`~/.config/omapdf/signatures/`)
- [x] Claude Code skill
- [x] Omarchy bar widget (`omapdf.bar`)
- [x] Test suite over generated sample documents

## v0.2 — smarter placement

- Signature-line detection: find "Signature:"/"Sign here"/rule lines and
  propose placements automatically (`omapdf sign --auto`)
- `ink` op (freehand strokes) and `stamp` op (APPROVED / initials / custom)
- Signature capture helper: draw in a window (or import from omasnap capture),
  auto-crop + transparent background
- `omapdf diff a.pdf b.pdf` — what changed between two versions (agent-friendly)

## v0.3 — the GUI (agent proposes, human confirms)

Native Wayland, Qt6 + poppler-qt6, omasnap-style: fast, minimal chrome, one
job. See gui/README.md. The signature move: an agent's dry-run placement
renders as a draggable ghost overlay — nudge, Enter, done. The GUI emits the
same ops the engine already speaks.

## v0.4 — cryptographic signing

PAdES digital signatures via pyHanko as an optional extra: certificate
management, visible + cryptographic signature in one op, verification
(`omapdf verify`). Visual and cryptographic signing stay clearly distinct in
the UX.

## Distribution

1. GitHub (omapdf/omapdf), AUR package (`packaging/PKGBUILD`)
2. Omarchy plugin listing for the bar widget
3. Pitch to the omarchy package repo once polished (the omasnap path)
