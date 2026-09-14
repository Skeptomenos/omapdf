# Trackpad signature capture

macOS Preview records signatures on the trackpad surface: the ink follows your
finger without clicking. omepreview aims for the same workflow on Linux.

## Behaviour

- **Default** (`omepreview sig draw`): trackpad mode — ink follows light touch
  or tablet proximity when the device exposes those axes.
- **Fallback** (`omepreview sig draw --click`): classic click-and-drag with the
  mouse (previous omapdf behaviour).
- **Editor**: choosing Sign with no saved signature opens the recorder inline.

Saved PNGs land in `~/.config/omepreview/signatures/` and are placed with the
existing `place_signature` op / Sign tool.

## Linux hardware limits

Most Linux touchpads do **not** report finger position without contact. True
hover signing (finger in the air above the pad) requires a proximity axis from
libinput — common on Wacom tablets, rare on laptop trackpads.

When hover is unavailable, omepreview uses **light contact**: pressure above
zero but below a firm press, without a button click. The UI hint states which
path your device is using.

## Implementation

- `omepreview.trackpad_sig` — capture policy (tested)
- `omepreview.draw` — GTK4 `EventControllerLegacy` (pressure), `EventControllerStylus`
  (proximity), plus `GestureDrag` fallback
