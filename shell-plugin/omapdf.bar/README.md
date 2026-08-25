# omapdf bar widget

A PDF quick-access pill for the Omarchy bar. Click it to pick a recent PDF
(from `~/Downloads`, `~/Documents`, `~/Desktop` — newest first) and open it
in the omapdf editor. When no PDFs are found it says so via a notification.

## Install

```bash
ln -s /path/to/omapdf/shell-plugin/omapdf.bar ~/.config/omarchy/plugins/omapdf.bar
omarchy bar put omapdf.bar --section right
```

Make sure `omapdf-pick` (from omapdf's `bin/`) is on your PATH.

## Settings

```bash
omarchy bar set omapdf.bar icon ""          # any Nerd Font glyph
omarchy bar set omapdf.bar command "my-cmd"   # override the click action
```

Set `OMAPDF_PICK_DIRS` (colon-separated) in your environment to change which
folders the picker searches.
