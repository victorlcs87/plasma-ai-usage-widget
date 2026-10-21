import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets

// Botão plano do Notch escuro: foco por teclado sempre visível (anel), hover discreto, estado marcado por
// forma (traço sob o texto) além da cor. Reutilizado por todos os controles do popup.
QQC2.AbstractButton {
    id: btn

    property color accent: Kirigami.Theme.highlightColor
    property string hint: ""  // dica (tooltip) e descrição acessível
    property string accessibleName: ""  // nome para leitor de tela quando o texto tem glifos ou se repete por cartão
    property alias iconItem: iconItem
    readonly property bool iconOnly: display === QQC2.AbstractButton.IconOnly && icon.name !== ""

    implicitWidth: row.implicitWidth + Kirigami.Units.smallSpacing * 3
    implicitHeight: Math.max(Kirigami.Units.gridUnit * 1.6, row.implicitHeight + Kirigami.Units.smallSpacing * 2)
    activeFocusOnTab: true
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45

    Accessible.role: Accessible.Button
    Accessible.name: accessibleName !== "" ? accessibleName : text
    Accessible.description: hint
    Accessible.checkable: checkable
    Accessible.checked: checked

    background: Rectangle {
        radius: 4
        color: btn.down ? Qt.rgba(1, 1, 1, 0.16) : btn.hovered ? Qt.rgba(1, 1, 1, 0.1) : btn.checked ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
        border.width: btn.visualFocus ? 2 : 0
        border.color: btn.accent
    }
    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                id: iconItem
                visible: btn.icon.name !== ""
                anchors.verticalCenter: parent.verticalCenter
                width: Kirigami.Units.iconSizes.small
                height: width
                source: btn.icon.name
                color: Presets.ui.fg
            }
            QQC2.Label {
                id: label
                visible: !btn.iconOnly
                anchors.verticalCenter: parent.verticalCenter
                text: btn.text
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                font.bold: btn.checked
                color: Presets.ui.fg
            }
        }
        Rectangle {  // marcado: traço sob o texto (forma além do negrito)
            visible: btn.checked
            anchors { horizontalCenter: parent.horizontalCenter; top: row.bottom; topMargin: 1 }
            width: row.width
            height: 2
            radius: 1
            color: btn.accent
        }
    }

    PlainTip { visible: (btn.hovered || btn.visualFocus) && btn.hint.length > 0; text: btn.hint }
    Keys.onReturnPressed: click()  // Enter também ativa (Espaço já é nativo)
    Keys.onEnterPressed: click()
}
