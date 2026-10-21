import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import "Presets.js" as Presets

// Notch compacto: pílula sempre escura com um Anel Duplo por provedor (Conta Ativa no Sistema).
Item {
    id: compactRoot

    property var plasmoidItem: null

    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
    readonly property var rings: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.compactModel : []
    readonly property int count: Math.max(1, rings.length)
    readonly property color accent: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.accentColor : Kirigami.Theme.highlightColor
    readonly property int totalInvites: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.totalInvites : 0
    readonly property string health: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.worstHealthStatus : ""

    // Tamanho-base do anel e folga da pílula; o anel encolhe até o mínimo para nunca ser cortado
    readonly property int ringBase: Kirigami.Units.iconSizes.medium
    readonly property int ringMin: Kirigami.Units.iconSizes.small
    readonly property int pad: Kirigami.Units.smallSpacing
    readonly property int gap: Kirigami.Units.smallSpacing
    readonly property int ringSize: Math.min(ringBase, Math.max(ringMin, (vertical ? width : height) - 2 * pad))

    function tr(text, arg) {
        return compactRoot.plasmoidItem ? compactRoot.plasmoidItem.safeI18n(text, arg) : text;
    }

    function runLength(size) { return count * size + (count - 1) * gap + 2 * pad; }

    Layout.minimumWidth: vertical ? ringMin + 2 * pad : runLength(ringMin)
    Layout.minimumHeight: vertical ? runLength(ringMin) : ringMin + 2 * pad
    Layout.preferredWidth: vertical ? ringBase + 2 * pad : runLength(ringBase)
    Layout.preferredHeight: vertical ? runLength(ringBase) : ringBase + 2 * pad

    Accessible.role: Accessible.Button
    Accessible.name: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipMainText : ""
    Accessible.description: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipSubText : ""

    // Pílula sempre escura, independente do tema
    Rectangle {
        id: pill
        anchors.centerIn: parent
        width: Math.min(parent.width, vertical ? compactRoot.ringSize + 2 * pad : compactRoot.runLength(compactRoot.ringSize))
        height: Math.min(parent.height, vertical ? compactRoot.runLength(compactRoot.ringSize) : compactRoot.ringSize + 2 * pad)
        radius: Math.min(width, height) / 2
        color: "#15171b"
        border.color: mouseArea.containsMouse ? compactRoot.accent : "#2a2d33"
        border.width: 1

        GridLayout {
            anchors.centerIn: parent
            columns: compactRoot.vertical ? 1 : compactRoot.count
            rowSpacing: compactRoot.gap
            columnSpacing: compactRoot.gap

            Repeater {
                model: compactRoot.rings
                delegate: DualRing {
                    required property var modelData
                    Layout.preferredWidth: compactRoot.ringSize
                    Layout.preferredHeight: compactRoot.ringSize
                    outerPct: modelData.outerPct
                    innerPct: modelData.innerPct
                    outerElapsed: modelData.outerElapsed
                    innerElapsed: modelData.innerElapsed
                    outerColor: Presets.levelColor(modelData.outerLevel, compactRoot.accent)
                    innerColor: Presets.levelColor(modelData.innerLevel, compactRoot.accent)
                    letter: modelData.letter
                    Accessible.role: Accessible.StaticText
                    Accessible.name: modelData.name
                    Accessible.description: modelData.description
                }
            }
        }

        // Sem provedor visível (todos ocultos): pílula mínima, o clique ainda abre o popup
        Rectangle {
            anchors.centerIn: parent
            visible: compactRoot.rings.length === 0
            width: compactRoot.ringSize * 0.4
            height: width
            radius: width / 2
            color: "#8a9099"
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor

        onClicked: {
            if (compactRoot.plasmoidItem) {
                compactRoot.plasmoidItem.expanded = !compactRoot.plasmoidItem.expanded;
            }
        }
    }

    // Selo de saúde (só quando há conta ativa com sessão expirada, sem configurar ou com erro)
    Rectangle {
        id: healthDot
        visible: compactRoot.health !== ""
        width: Math.max(8, Kirigami.Units.smallSpacing * 1.8)
        height: width
        radius: width / 2
        anchors.right: pill.right
        anchors.bottom: pill.bottom
        color: compactRoot.health === "session_expired" ? "#f5a524"
             : compactRoot.health === "not_configured" ? "#8a9099" : "#ff4d4f"
        border.color: "#15171b"
        border.width: 1.5
        Accessible.name: compactRoot.health === "session_expired" ? compactRoot.tr("Sessão expirada")
                       : compactRoot.health === "not_configured" ? compactRoot.tr("Conta não configurada") : compactRoot.tr("Erro na conta")
    }

    // Selo numérico de convites
    Rectangle {
        id: inviteBadge
        visible: compactRoot.totalInvites > 0
        anchors.right: pill.right
        anchors.top: pill.top
        anchors.margins: -1

        implicitHeight: Math.max(14, Kirigami.Units.gridUnit * 0.9)
        implicitWidth: Math.max(inviteLabel.implicitWidth + 6, implicitHeight)
        radius: implicitHeight / 2
        color: "#d35400"
        border.color: "#15171b"
        border.width: 1
        Accessible.name: compactRoot.tr("%1 convites disponíveis", compactRoot.totalInvites)

        QQC2.Label {
            id: inviteLabel
            anchors.centerIn: parent
            text: String(compactRoot.totalInvites)
            font.bold: true
            font.pointSize: Kirigami.Theme.smallFont.pointSize * 0.75
            color: "white"
            textFormat: Text.PlainText
        }
    }
}
