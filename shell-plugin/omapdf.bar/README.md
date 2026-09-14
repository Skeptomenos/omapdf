# omepreview.bar — PDF quick-access for the Omarchy bar

A PDF pill for the Omarchy top bar. Click it, pick a recent PDF (from
`~/Downloads`, `~/Documents`, `~/Desktop` — newest first), and it opens:
in the [omepreview](https://github.com/Skeptomenos/omepreview) editor when
installed (read, annotate, sign), otherwise in your system PDF viewer. When
no PDFs are found it tells you via a notification.

Works standalone — omepreview itself is optional but recommended: it's the
PDF editor this widget is the front door to.

The plugin directory is still `omapdf.bar` (Omarchy module id) so existing
`omarchy bar put omapdf.bar` configs keep working.

## Install

From this repo:

```bash
ln -s "$PWD/shell-plugin/omapdf.bar" ~/.config/omarchy/plugins/omapdf.bar
omarchy bar put omapdf.bar --section right
```

## Settings

```bash
omarchy bar set omapdf.bar icon ""          # any Nerd Font glyph
omarchy bar set omapdf.bar command "my-cmd"   # override the click action
```

Set `OMEPREVIEW_PICK_DIRS` (colon-separated) in your environment to change
which folders the picker searches. `OMAPDF_PICK_DIRS` is still accepted as
a deprecated alias.

## License

AGPL-3.0-or-later.
