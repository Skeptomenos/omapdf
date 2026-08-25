# omapdf GUI (v0.3 — not started)

A native Wayland viewer/confirmer in the omasnap mold: Qt6 + poppler-qt6,
minimal chrome, keyboard-first, themable to Omarchy.

## Design principles

1. **A client, not a fork.** The GUI builds the same JSON ops the CLI and MCP
   server produce and hands them to the same engine. No GUI-only features.
2. **Agent proposes, human confirms.** A dry-run op report (e.g. a signature
   placement rect) renders as a draggable ghost overlay. Arrow keys nudge,
   Enter applies, Esc rejects. This is the tool's signature interaction.
3. **Preview.app speed.** Open instantly, thumbnails sidebar, spacebar scroll,
   `h` highlight-mode, `s` drop signature, `Ctrl+S` save. Nothing else in v1.

## Planned layout

```
gui/
├── CMakeLists.txt
├── src/
│   ├── main.cpp          # arg parsing: omapdf-gui doc.pdf [--confirm ops.json]
│   ├── DocumentView.*    # poppler render + annotation overlay
│   ├── OpBridge.*        # build op JSON, shell out to `omapdf apply`
│   └── GhostOverlay.*    # dry-run placements as draggable proposals
└── qml/ or widgets — TBD
```

Until this lands, `omapdf open` hands off to the desktop's default viewer.
