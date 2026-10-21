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

    readonly property bool widgetUpdate: !!(compactRoot.plasmoidItem && compactRoot.plasmoidItem.updateInfo && compactRoot.plasmoidItem.updateInfo.widget)
    readonly property bool cliUpdate: rings.some(function (r) { return !!r.update; })

    // Tamanho-base do anel e folga da pílula; o anel encolhe até o mínimo (cabe a inicial em 8 px)
    readonly property int ringBase: Kirigami.Units.iconSizes.smallMedium
    readonly property int ringMin: Math.round(Kirigami.Units.gridUnit * 1.1)
    readonly property int pad: Kirigami.Units.smallSpacing
    readonly property int gap: Kirigami.Units.smallSpacing
    readonly property int ringSize: Math.min(ringBase, Math.max(ringMin, (vertical ? width : height) - 2 * pad))
    // Selos entram no fluxo da pílula, depois dos anéis: nunca cobrem um anel
    readonly property int badgeLength: (health !== "" ? healthDot.implicitWidth + gap : 0)
        + (cliUpdate ? updateDot.implicitWidth + gap : 0)
        + (widgetUpdate ? (vertical ? widgetBadge.implicitHeight : widgetBadge.implicitWidth) + gap : 0)
        + (totalInvites > 0 ? (vertical ? inviteBadge.implicitHeight : inviteBadge.implicitWidth) + gap : 0)

    function tr(text, arg) {
        return compactRoot.plasmoidItem ? compactRoot.plasmoidItem.safeI18n(text, arg) : text;
    }

    function runLength(size) { return count * size + (count - 1) * gap + badgeLength + 2 * pad; }

    // Clique do mouse: abre/fixa/solta (main.qml); teclado: abre/fecha como antes
    function toggle() {
        if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.expanded = !compactRoot.plasmoidItem.expanded;
    }

    function closePopup() {
        if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.closePopup();
    }

    Layout.minimumWidth: vertical ? ringMin + 2 * pad : runLength(ringMin)
    Layout.minimumHeight: vertical ? runLength(ringMin) : ringMin + 2 * pad
    Layout.preferredWidth: vertical ? ringBase + 2 * pad : runLength(ringBase)
    Layout.preferredHeight: vertical ? runLength(ringBase) : ringBase + 2 * pad

    activeFocusOnTab: true
    // Destruído com o mouse em cima (formFactor, reconfiguração): não deixa o hover preso
    Component.onDestruction: if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.setPillHovered(false)
    Keys.onReturnPressed: toggle()
    Keys.onEnterPressed: toggle()
    Keys.onSpacePressed: toggle()
    Keys.onEscapePressed: closePopup()

    Accessible.role: Accessible.Button
    Accessible.name: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipMainText : ""
    Accessible.description: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipSubText : ""
    Accessible.onPressAction: toggle()

    // Pílula sempre escura, independente do tema
    Rectangle {
        id: pill
        anchors.centerIn: parent
        width: Math.min(parent.width, vertical ? compactRoot.ringSize + 2 * pad : compactRoot.runLength(compactRoot.ringSize))
        height: Math.min(parent.height, vertical ? compactRoot.runLength(compactRoot.ringSize) : compactRoot.ringSize + 2 * pad)
        radius: Math.min(width, height) / 2
        color: "#15171b"
        border.color: mouseArea.containsMouse || compactRoot.activeFocus ? compactRoot.accent : "#2a2d33"
        border.width: 1

        GridLayout {
            anchors.centerIn: parent
            columns: compactRoot.vertical ? 1 : compactRoot.count + 4
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
                    outerLevel: modelData.outerLevel
                    innerLevel: modelData.innerLevel
                    outerColor: Presets.levelColor(modelData.outerLevel, compactRoot.accent)
                    innerColor: Presets.levelColor(modelData.innerLevel, compactRoot.accent)
                    letter: modelData.letter
                    Accessible.role: Accessible.StaticText
                    Accessible.name: modelData.name
                    Accessible.description: modelData.description
                }
            }

            // Sem provedor visível (todos ocultos): ponto neutro; o clique ainda abre o popup
            Item {
                visible: compactRoot.rings.length === 0
                Layout.preferredWidth: compactRoot.ringSize
                Layout.preferredHeight: compactRoot.ringSize
                Rectangle {
                    anchors.centerIn: parent
                    implicitWidth: parent.width * 0.4
                    width: implicitWidth
                    height: width
                    radius: width / 2
                    color: "#8a9099"
                }
            }

            // Selo de saúde (só com Conta Ativa com sessão expirada, sem configurar ou com erro)
            Rectangle {
                id: healthDot
                visible: compactRoot.health !== ""
                Layout.alignment: Qt.AlignCenter
                implicitWidth: Math.max(8, Kirigami.Units.smallSpacing * 1.8)
                implicitHeight: implicitWidth
                radius: implicitWidth / 2
                color: compactRoot.health === "session_expired" ? "#f5a524"
                     : compactRoot.health === "not_configured" ? "#8a9099" : "#ff4d4f"
                Accessible.name: compactRoot.health === "session_expired" ? compactRoot.tr("Sessão expirada")
                               : compactRoot.health === "not_configured" ? compactRoot.tr("Conta não configurada") : compactRoot.tr("Erro na conta")
            }

            // Ponto azul: nova versão de Claude Code, Codex ou Gemini CLI
            Rectangle {
                id: updateDot
                visible: compactRoot.cliUpdate
                Layout.alignment: Qt.AlignCenter
                implicitWidth: Math.max(8, Kirigami.Units.smallSpacing * 1.8)
                implicitHeight: implicitWidth
                radius: implicitWidth / 2
                color: Kirigami.Theme.highlightColor  // sobre a pílula escura (#15171b) passa de 4,5:1 nos temas Breeze
                Accessible.role: Accessible.Indicator
                Accessible.name: compactRoot.tr("Nova versão de CLI disponível")
                HoverHandler { id: updateDotHover }
                QQC2.ToolTip.visible: updateDotHover.hovered
                QQC2.ToolTip.text: compactRoot.tr("Nova versão de CLI disponível")
            }

            // Selo: nova versão do widget
            Rectangle {
                id: widgetBadge
                visible: compactRoot.widgetUpdate
                Layout.alignment: Qt.AlignCenter
                implicitHeight: Math.max(14, Kirigami.Units.gridUnit * 0.9)
                implicitWidth: implicitHeight
                radius: implicitHeight / 2
                color: Kirigami.Theme.highlightColor
                Accessible.role: Accessible.Indicator
                Accessible.name: compactRoot.tr("Nova versão do widget disponível")

                QQC2.Label {
                    anchors.centerIn: parent
                    text: "\u2191"
                    font.bold: true
                    font.pointSize: Kirigami.Theme.smallFont.pointSize * 0.8
                    color: Kirigami.Theme.highlightedTextColor
                    textFormat: Text.PlainText
                }
            }

            // Selo numérico de convites
            Rectangle {
                id: inviteBadge
                visible: compactRoot.totalInvites > 0
                Layout.alignment: Qt.AlignCenter
                implicitHeight: Math.max(14, Kirigami.Units.gridUnit * 0.9)
                implicitWidth: Math.max(inviteLabel.implicitWidth + 6, implicitHeight)
                radius: implicitHeight / 2
                color: "#d35400"
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
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onContainsMouseChanged: if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.setPillHovered(containsMouse)
        onClicked: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.pillClicked() : compactRoot.toggle()
    }
}
