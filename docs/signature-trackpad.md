# Trackpad signature capture

macOS Preview records a signature on the trackpad: **Space** starts, a finger
**on the pad** moving is ink (a click or press-down is not required), **Enter**
saves. Re-record is required to replace it — Space while recording or after a
take clears and starts over. omepreview matches that workflow. Hover-in-air is
not the goal and is not implemented.

The on-screen pad is the whole physical trackpad as an **absolute 2D surface**.
A finger down at the top-left of the hardware pad inks the top-left of the
graphic; lift, then a finger down elsewhere starts a **new** stroke at that
mapped location. Relative pointer deltas are not the model (they leave the
cursor at the last ink point after a lift).

## Behaviour

- **Default** (`omepreview sig draw`): the window *is* the trackpad (rounded
  pad surface). Space arms recording. Rest a finger and **move** — ink follows
  live at the **absolute** pad location. Touching is required; clicking is not.
  Lifting the finger ends the current stroke (no connecting line across a lift).
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

## Linux / Wayland: absolute mapping

GTK pointer events on Wayland (and usually on X11) are **relative**. After you
lift a finger the compositor leaves the cursor where it was, so the next
contact would keep drawing from the last ink point. That is not Preview.

While recording is armed, omepreview opens the touchpad’s evdev node
(`/dev/input/event*`) **without grabbing it** (Hyprland/libinput keep getting
events) and reads:

1. `ABS_MT_POSITION_X` / `ABS_MT_POSITION_Y` (multitouch protocol B, preferred)
2. else `ABS_X` / `ABS_Y` plus `BTN_TOUCH` / `BTN_TOOL_FINGER`

The device abs range is scaled onto the on-screen pad widget (independent X/Y,
top-left origin). `BTN_TOUCH` / `ABS_MT_TRACKING_ID == -1` ends the stroke.

Relative GTK motion is used **only** when no abs axes can be opened (no
touchpad node, or permission denied). `--click` never uses evdev.

### `/dev/input` permissions

Absolute mapping needs to `open()` the touchpad node.

- A local graphical seat (Omarchy/Hyprland included) often already has
  **logind `uaccess` ACLs** on `/dev/input/event*`, so the logged-in user
  can read the pad without extra groups.
- If open fails (`PermissionError` / EACCES), add your user to the `input`
  group and re-login:

      sudo usermod -aG input $USER

  Then log out of the session (not just a new terminal) so group membership
  and device ACLs apply. The recorder shows a relative-pointer fallback hint
  until that works.

Do not `evdev` grab (`EVIOCGRAB`) the pad — that would steal it from the
compositor.

## Implementation

- `omepreview.abs_pad` — evdev discovery, MT parser, abs→pad mapping (tested)
- `omepreview.trackpad_sig` — capture policy, Space/Enter session, SVG
  export, abs contact up/down (tested)
- `omepreview.draw` — GTK4 trackpad-shaped window, live ink, abs reader
  while armed; `EventControllerLegacy` ignores `event=None`
- `omepreview.signature` — SVG store under `~/.config/omepreview/signatures/`
