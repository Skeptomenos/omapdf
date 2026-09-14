# Trackpad signature capture

macOS Preview records a signature on the trackpad: **Space** starts, a finger
**on the pad** moving is ink (a click or press-down is not required), **Enter**
saves. Re-record is required to replace it — Space while recording or after a
take clears and starts over. omepreview matches that workflow. Hover-in-air is
not the goal and is not implemented.

## Behaviour

- **Default** (`omepreview sig draw`): the window *is* the trackpad (rounded
  pad surface). Space arms recording and grabs the pointer so finger motion
  maps onto that pad instead of wandering the desktop. Rest a finger and
  **move** — ink follows live. Touching is required; clicking is not.
- **Fallback** (`omepreview sig draw --click`): Space still arms; then
  classic mouse click-and-drag on the pad.
- **Enter** writes an **SVG** to `~/.config/omepreview/signatures/` (name
  `default` unless `--name` is given).
- **Space** while armed or after ink: clear and re-arm. There is no
  incremental edit of a saved signature — record again.
- **Editor**: Sign opens a dropdown of saved signatures. Select one and
  **drag it onto the page** (or click to place). Record new / re-record from
  that menu.

`place_signature` and the Sign tool consume the stored SVG.

## Keys

| Key | Action |
|-----|--------|
| Space | Start recording; if already recording or inked, clear and start over |
| Enter | Save SVG (no-op until there is a stroke) |
| Escape | Cancel without saving |

## Linux notes

Laptop trackpads already move the pointer without BUTTON1. That motion is
the ink while the recorder is armed. A click is not part of the model.

GTK 4 has no portable `gdk_seat_grab`. On X11 the recorder confines the
pointer to the pad window (`XGrabPointer` + `confine_to`). If confine is
unavailable (typical on Wayland), motion is mapped with relative deltas so
ink stays on the pad even if the OS cursor is not.

## Implementation

- `omepreview.trackpad_sig` — capture policy, Space/Enter session, SVG
  export (tested)
- `omepreview.draw` — GTK4 trackpad-shaped window, live ink, pointer grab
- `omepreview.signature` — SVG store under `~/.config/omepreview/signatures/`
