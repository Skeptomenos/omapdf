# omapdf.bar — PDF quick-access for the Omarchy bar

A PDF pill for the Omarchy top bar. Click it, pick a recent PDF (from
`~/Downloads`, `~/Documents`, `~/Desktop` — newest first), and it opens:
in the [omapdf](https://github.com/pbergin11/omapdf) editor when installed
(read, annotate, sign, ask your agent about it), otherwise in your system
PDF viewer. When no PDFs are found it tells you via a notification.

Works standalone — omapdf itself is optional but recommended: it's the
agent-native PDF editor this widget is the front door to.

## Install

```bash
omarchy plugin add https://github.com/pbergin11/omapdf-bar --enable
omarchy bar put omapdf.bar --section right
```

Or manually: clone into `~/.config/omarchy/plugins/omapdf.bar` and run the
`omarchy bar put` line.

## Settings

```bash
omarchy bar set omapdf.bar icon ""          # any Nerd Font glyph
omarchy bar set omapdf.bar command "my-cmd"   # override the click action
```

Set `OMAPDF_PICK_DIRS` (colon-separated) in your environment to change
which folders the picker searches.

## License

AGPL-3.0-or-later.
