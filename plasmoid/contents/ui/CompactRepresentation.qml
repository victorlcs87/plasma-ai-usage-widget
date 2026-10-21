import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle

// Notch compacto: pílula sempre escura com um Anel Duplo por provedor (Conta Ativa no Sistema).
Item {
    id: compactRoot

    property var plasmoidItem: null

    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
    readonly property var rings: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.compactModel : []
    readonly property int count: Math.max(1, rings.length)
    readonly property color accent: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.accentColor : Kirigami.Theme.highlightColor
    readonly property int totalInvites: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.totalInvites : 0
    // Modo "ocultar sem o processo da CLI": pílula some e resta uma fatia fina (alvo do botão direito e do clique)
    readonly property bool idle: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.idleHidden === true : false
    readonly property string health: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.worstHealthStatus : ""

    // Estilo, modo, centro, tamanho e margem (ticket 32): valores inválidos caem no padrão (PanelStyle.config)
    readonly property var panel: PanelStyle.config(Plasmoid.configuration)
    readonly property int ringBase: Kirigami.Units.iconSizes.smallMedium
    readonly property int ringMin: Math.round(Kirigami.Units.gridUnit * 1.1)
    readonly property int pad: panel.margin
    readonly property int gap: Kirigami.Units.smallSpacing
    // Com tamanho < 100%, o piso do anel acompanha o tamanho escolhido
    readonly property int minUnit: Math.min(ringMin, Math.round(ringBase * panel.scale))
    readonly property var geoOpts: ({ style: panel.style, mode: panel.mode, vertical: vertical, pad: pad, gap: gap,
                                      base: ringBase, scale: panel.scale, minUnit: minUnit })
    // Espessura mínima e preferida do painel (o estilo Ring soma o fundo próprio de cada item)
    readonly property int ringExtra: panel.style === "ring" ? 4 : 0
    readonly property int crossMinBase: minUnit + 2 * pad + ringExtra
    // Nunca menor que o item no menor tamanho de fonte (ex.: Bar vertical precisa de mais largura)
    readonly property var geoFloor: PanelStyle.layout(geoOpts, crossMinBase)
    readonly property int crossMin: Math.max(crossMinBase, (vertical ? geoFloor.w : geoFloor.h) + 2 * pad)
    readonly property int crossPref: Math.round(ringBase * panel.scale) + 2 * pad + ringExtra
    // Tamanho de cada item: atual (encolhe até caber, sem corte) e no mínimo; o comprimento preferido
    // acompanha o tamanho atual
    readonly property var geo: PanelStyle.layout(geoOpts, vertical ? width : height)
    readonly property var geoMin: PanelStyle.layout(geoOpts, crossMin)
    // Selos entram no fluxo da pílula, depois dos itens: nunca cobrem um anel
    readonly property int badgeLength: (health !== "" ? healthDot.implicitWidth + gap : 0)
        + (totalInvites > 0 ? (vertical ? inviteBadge.implicitHeight : inviteBadge.implicitWidth) + gap : 0)

    function tr(text, arg) {
        return compactRoot.plasmoidItem ? compactRoot.plasmoidItem.safeI18n(text, arg) : text;
    }

    function runLength(g) { return count * (vertical ? g.h : g.w) + (count - 1) * gap + badgeLength + 2 * pad; }

    // Clique do mouse: abre/fixa/solta (main.qml); teclado: abre/fecha como antes
    function toggle() {
        if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.expanded = !compactRoot.plasmoidItem.expanded;
    }

    function closePopup() {
        if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.closePopup();
    }

    readonly property int sliver: Kirigami.Units.gridUnit
    Layout.minimumWidth: vertical ? crossMin : (idle ? sliver : runLength(geoMin))
    Layout.minimumHeight: vertical ? (idle ? sliver : runLength(geoMin)) : crossMin
    Layout.preferredWidth: vertical ? crossPref : (idle ? sliver : runLength(geo))
    Layout.preferredHeight: vertical ? (idle ? sliver : runLength(geo)) : crossPref

    activeFocusOnTab: true
    // Destruído com o mouse em cima (formFactor, reconfiguração): não deixa o hover preso
    Component.onDestruction: if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.setPillHovered(false)
    Keys.onReturnPressed: toggle()
    Keys.onEnterPressed: toggle()
    Keys.onSpacePressed: toggle()
    Keys.onEscapePressed: closePopup()

    Accessible.role: Accessible.Button
    Accessible.name: compactRoot.idle ? compactRoot.tr("Monitor de IA oculto: nenhuma CLI em execução. Ative para abrir")
        : (compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipMainText : "")
    Accessible.description: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipSubText : ""
    Accessible.onPressAction: toggle()

    // Pílula sempre escura, independente do tema
    Rectangle {
        id: pill
        visible: !compactRoot.idle
        anchors.centerIn: parent
        width: Math.min(parent.width, vertical ? compactRoot.geo.w + 2 * pad : compactRoot.runLength(compactRoot.geo))
        height: Math.min(parent.height, vertical ? compactRoot.runLength(compactRoot.geo) : compactRoot.geo.h + 2 * pad)
        radius: compactRoot.panel.style === "text" || compactRoot.panel.style === "bar"
            ? Math.min(Kirigami.Units.gridUnit * 0.5, Math.min(width, height) / 2) : Math.min(width, height) / 2
        // Ring: sem cápsula comum (cada item tem fundo escuro próprio); a borda segue aparecendo no foco/hover
        color: compactRoot.panel.style === "ring" ? "transparent" : "#15171b"
        border.color: mouseArea.containsMouse || compactRoot.activeFocus ? compactRoot.accent
            : (compactRoot.panel.style === "ring" ? "transparent" : "#2a2d33")
        border.width: 1

        GridLayout {
            anchors.centerIn: parent
            columns: compactRoot.vertical ? 1 : compactRoot.count + 2
            rowSpacing: compactRoot.gap
            columnSpacing: compactRoot.gap

            Repeater {
                model: compactRoot.rings
                delegate: PanelItem {
                    required property var modelData
                    Layout.preferredWidth: compactRoot.geo.w
                    Layout.preferredHeight: compactRoot.geo.h
                    m: modelData
                    panelStyle: compactRoot.panel.style
                    mode: compactRoot.panel.mode
                    center: compactRoot.panel.center
                    vertical: compactRoot.vertical
                    geo: compactRoot.geo
                    gap: compactRoot.gap
                    accent: compactRoot.accent
                    active: !compactRoot.idle
                    reducedMotion: Kirigami.Units.longDuration === 0  // animações desligadas no Plasma
                    Accessible.role: Accessible.StaticText
                    Accessible.name: modelData.name
                    Accessible.description: modelData.description
                }
            }

            // Sem provedor visível (todos ocultos): ponto neutro; o clique ainda abre o popup
            Item {
                visible: compactRoot.rings.length === 0
                Layout.preferredWidth: Math.min(compactRoot.geo.w, compactRoot.geo.h)
                Layout.preferredHeight: Math.min(compactRoot.geo.w, compactRoot.geo.h)
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

    Rectangle {
        visible: compactRoot.idle
        anchors.centerIn: parent
        width: vertical ? parent.width * 0.7 : Math.max(4, compactRoot.sliver / 3)
        height: vertical ? Math.max(4, compactRoot.sliver / 3) : parent.height * 0.7
        radius: Math.min(width, height) / 2
        color: compactRoot.accent
        opacity: mouseArea.containsMouse ? 1 : 0.8
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
