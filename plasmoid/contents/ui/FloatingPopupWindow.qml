import QtQuick
import QtQuick.Layouts

// Popup do Notch flutuante: o mesmo FullRepresentation, ancorado na pílula (FloatingGeometry.popupRect)
FloatingFrame {
    id: win
    interactive: true
    overlay: true
    readonly property size want: Qt.size(full.Layout.preferredWidth, full.Layout.preferredHeight)
    property bool hadFocus: false

    // Clicar fora fecha (só se o popup chegou a ter foco), como o popup nativo; fixado ou com o mouse na pílula, não
    onActiveChanged: {
        if (active) hadFocus = true;
        else if (hadFocus) {
            hadFocus = false;
            var p = host ? host.plasmoidItem : null;
            if (p && p.open && !p.pinned && !p.pillHovered) p.closePopup();
        }
    }
    onVisibleChanged: if (!visible) hadFocus = false

    FullRepresentation {
        id: full
        anchors.fill: parent
        plasmoidItem: win.host ? win.host.plasmoidItem : null
    }
}
