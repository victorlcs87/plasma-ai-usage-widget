import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.plasmoid
import "I18n.js" as I18n

// Pílula flutuante: o MESMO CompactRepresentation do painel (anéis, selos, hover, clique, ocultar), com a
// orientação e o tamanho do Notch flutuante. Arrastar ao longo da borda, setas (8 px, Shift 32 px) e Home
// (recentrar) também funcionam pelo teclado.
FloatingFrame {
    id: win
    interactive: true
    readonly property size want: Qt.size(pill.Layout.preferredWidth, pill.Layout.preferredHeight)
    readonly property bool vertical: host ? host.cfg.vertical : false

    Item {
        anchors.fill: parent
        focus: true
        Keys.onPressed: (event) => {
            var step = (event.modifiers & Qt.ShiftModifier) ? 32 : 8;
            var d = 0;
            if (event.key === (win.vertical ? Qt.Key_Up : Qt.Key_Left)) d = -step;
            else if (event.key === (win.vertical ? Qt.Key_Down : Qt.Key_Right)) d = step;
            else if (event.key === Qt.Key_Home) { win.host.recenter(); event.accepted = true; return; }
            else return;
            win.host.nudge(d);
            event.accepted = true;
        }

        CompactRepresentation {
            id: pill
            anchors.fill: parent
            hosted: true
            plasmoidItem: win.host ? win.host.plasmoidItem : null
            forceVertical: win.vertical ? 1 : 0
            panelOverride: win.host ? win.host.panelCfg : null
        }

        // Botão direito: Configurar (o mesmo caminho de volta do menu do widget no painel) e a atualização do widget, que
        // só busca ou abre a confirmação no popup (requestWidgetUpdate); a janela da pílula é pequena, então o menu é uma janela própria
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: menu.popup()
        }
        QQC2.Menu {
            id: menu
            objectName: "pillMenu"
            popupType: QQC2.Popup.Window
            QQC2.MenuItem {
                objectName: "pillMenuUpdate"
                text: win.host && win.host.plasmoidItem ? win.host.plasmoidItem.widgetUpdateActionText : ""
                enabled: Boolean(win.host && win.host.plasmoidItem && win.host.plasmoidItem.widgetUpdateActionEnabled)
                icon.name: "update-none"
                onTriggered: win.host.plasmoidItem.requestWidgetUpdate()
            }
            QQC2.MenuItem {
                objectName: "pillMenuConfigure"
                text: I18n.tr("Configure…")
                icon.name: "configure"
                onTriggered: Plasmoid.internalAction("configure").trigger()
            }
        }

        DragHandler {
            target: null
            acceptedButtons: Qt.LeftButton
            // Offset novo = o já aplicado + o quanto o ponteiro saiu do ponto do clique (a janela acompanha o
            // ponteiro, então o desvio tende a zero); a configuração só é gravada ao soltar
            onCentroidChanged: if (active) win.host.dragBy(win.vertical ? centroid.position.y - centroid.pressPosition.y
                                                                          : centroid.position.x - centroid.pressPosition.x)
            onActiveChanged: if (!active) win.host.dragEnd()
        }
    }
}
