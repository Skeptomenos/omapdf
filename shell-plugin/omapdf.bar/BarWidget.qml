import QtQuick
import qs.Commons
import qs.Ui

// omapdf pill: a PDF glyph in the bar. Click runs the picker (recent PDFs
// from Downloads/Documents/Desktop) and opens the chosen file.
//
// Settings (omarchy bar set omapdf.bar <key> <value>):
//   icon     - glyph shown in the bar (default: nf-fa-file_pdf)
//   command  - what a click runs (default: omapdf-pick)
BarWidget {
  id: root
  moduleName: "omapdf.bar"

  readonly property string icon: setting("icon", "")
  readonly property string command: setting("command", "omapdf-pick")

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.icon
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    tooltipText: "Open a PDF (omapdf)"
    onPressed: if (root.bar) root.bar.run(root.command)
  }
}
