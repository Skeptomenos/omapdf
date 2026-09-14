import QtQuick
import qs.Commons
import qs.Ui

// omapreview pill: a PDF glyph in the bar. Click runs the bundled picker
// (recent PDFs from Downloads/Documents/Desktop) and opens the chosen file
// — in the omapreview editor when installed, else the system PDF handler.
//
// Settings (omarchy bar set omapdf.bar <key> <value>):
//   icon     - glyph shown in the bar (default: nf-fa-file_pdf)
//   command  - what a click runs (default: the bundled pick.sh)
BarWidget {
  id: root
  moduleName: "omapdf.bar"

  // The plugin's own folder, so the bundled script needs no install step.
  readonly property string pluginDir: {
    var url = Qt.resolvedUrl(".").toString()
    return url.startsWith("file://") ? url.substring(7) : url
  }
  readonly property string icon: setting("icon", "")
  readonly property string command: setting("command", "bash " + pluginDir + "pick.sh")

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
