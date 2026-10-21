import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle
import "ViewPrefs.js" as ViewPrefs
import "I18n.js" as I18n

// Notch compacto: pílula sempre escura com um Anel Duplo por provedor (Conta Ativa no Sistema).
Item {
    id: compactRoot

    property var plasmoidItem: null

    // Notch flutuante (ticket 41): a janela flutuante hospeda este mesmo componente (hosted) e força a orientação
    // e o tamanho; com o flutuante ativo, o widget no painel vira só um marcador (miniatura) que mantém o menu
    // do botão direito (Configurar) e abre/fecha o mesmo popup. Sem isso, nada muda.
    property bool hosted: false
    property int forceVertical: -1      // -1 = segue o painel; 0 horizontal; 1 vertical
    property var panelOverride: null    // {style, mode, center, scale, margin} do flutuante
    readonly property bool marker: !hosted && !!compactRoot.plasmoidItem && compactRoot.plasmoidItem.floatingActive === true
    readonly property bool vertical: forceVertical >= 0 ? forceVertical === 1 : Plasmoid.formFactor === PlasmaCore.Types.Vertical
    readonly property var rings: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.compactModel : []
    readonly property int count: Math.max(1, rings.length)
    readonly property color accent: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.accentColor : Kirigami.Theme.highlightColor
    readonly property int totalInvites: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.totalInvites : 0
    // Modo "ocultar sem o processo da CLI": pílula some e resta uma fatia fina (alvo do botão direito e do clique)
    readonly property bool idle: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.idleHidden === true : false
    readonly property string health: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.worstHealthStatus : ""

    // Estilo, modo, centro, tamanho e margem (ticket 32): valores inválidos caem no padrão (PanelStyle.config)
    readonly property var panel: panelOverride ? panelOverride : PanelStyle.config(Plasmoid.configuration)
    readonly property bool remaining: ViewPrefs.config(Plasmoid.configuration).remaining  // usado/restante (ticket 33)
    readonly property bool widgetUpdate: !!(compactRoot.plasmoidItem && compactRoot.plasmoidItem.updateInfo && compactRoot.plasmoidItem.updateInfo.widget)
    readonly property color updateColor: Presets.onPill(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b)
    readonly property bool cliUpdate: rings.some(function (r) { return !!r.update; })

    readonly property int ringBase: Kirigami.Units.iconSizes.smallMedium
    readonly property int ringMin: Math.round(Kirigami.Units.gridUnit * 1.1)
    // Margem: automática (smallSpacing, como antes) até o usuário escolher um valor
    readonly property int pad: panel.margin < 0 ? Kirigami.Units.smallSpacing : panel.margin
    readonly property int gap: Kirigami.Units.smallSpacing
    // Com tamanho < 100%, o piso do anel acompanha o tamanho escolhido
    readonly property int minUnit: Math.min(ringMin, Math.round(ringBase * panel.scale))
    readonly property var reqOpts: ({ style: panel.style, mode: panel.mode, center: panel.center, vertical: vertical, pad: pad, gap: gap,
                                      base: ringBase, scale: panel.scale, minUnit: minUnit })
    // Estilo e centro em uso: se a espessura do painel não comporta o pedido, degrada (Bar -> Text -> Pílula;
    // centro com % -> logo) em vez de cortar
    // effC (só pela espessura) dá o mínimo e o preferido que o painel recebe; eff também degrada pelo comprimento
    // realmente disponível (largura no painel horizontal, altura no vertical) e é o que se desenha. Preferido
    // fora do degradê por comprimento: senão o painel, ao receber menos, nunca mais devolveria o estilo pedido.
    readonly property var effC: PanelStyle.effective(reqOpts, vertical ? width : height)
    readonly property var eff: PanelStyle.effective(reqOpts, vertical ? width : height, vertical ? height : width,
                                                    function (oo) { return compactRoot.runLength(PanelStyle.layout(oo, vertical ? compactRoot.width : compactRoot.height), oo.style); })
    readonly property string style: eff.style
    function optsFor(e) { return { style: e.style, mode: panel.mode, center: e.center, vertical: vertical, pad: pad, gap: gap,
                                   base: ringBase, scale: panel.scale, minUnit: minUnit }; }
    readonly property var geoOpts: optsFor(eff)
    readonly property var geoOptsC: optsFor(effC)
    // Espessura mínima e preferida do painel (a preferida nunca fica abaixo da mínima)
    readonly property int crossMin: PanelStyle.minCross(geoOptsC)
    readonly property int crossPref: Math.max(crossMin, Math.round(ringBase * panel.scale) + 2 * pad + (effC.style === "ring" ? 4 : 0))
    // Tamanho de cada item: o desenhado (encolhe até caber, sem corte), o preferido e o mínimo
    readonly property var geo: PanelStyle.layout(geoOpts, vertical ? width : height)
    readonly property var geoPref: PanelStyle.layout(geoOptsC, vertical ? width : height)
    readonly property var geoMin: PanelStyle.layout(geoOptsC, crossMin)
    // Selos entram no fluxo da pílula, depois dos itens (num grupo: no Ring, com fundo escuro próprio)
    readonly property int badgeCount: (health !== "" ? 1 : 0) + (cliUpdate ? 1 : 0) + (widgetUpdate ? 1 : 0) + (totalInvites > 0 ? 1 : 0)
    readonly property int badgePad: style === "ring" ? 3 : 0
    function badgeLengthFor(st) { return badgeCount === 0 ? 0 : badgeInner + 2 * (st === "ring" ? 3 : 0); }
    readonly property int badgeInner: gap
        + (health !== "" ? healthDot.implicitWidth + gap : 0)
        + (cliUpdate ? updateDot.implicitWidth + gap : 0)
        + (widgetUpdate ? (vertical ? widgetBadge.implicitHeight : widgetBadge.implicitWidth) + gap : 0)
        + (totalInvites > 0 ? (vertical ? inviteBadge.implicitHeight : inviteBadge.implicitWidth) + gap : 0) - gap

    function runLength(g, st) { return count * (vertical ? g.h : g.w) + (count - 1) * gap + badgeLengthFor(st) + 2 * pad; }

    // Clique do mouse: abre/fixa/solta (main.qml); teclado: abre/fecha como antes
    function toggle() {
        if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.expanded = !compactRoot.plasmoidItem.expanded;
    }

    function closePopup() {
        if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.closePopup();
    }

    readonly property int sliver: Kirigami.Units.gridUnit
    readonly property int markerSize: Kirigami.Units.iconSizes.smallMedium
    Layout.minimumWidth: marker ? markerSize : vertical ? crossMin : (idle ? sliver : runLength(geoMin, effC.style))
    Layout.minimumHeight: marker ? markerSize : vertical ? (idle ? sliver : runLength(geoMin, effC.style)) : crossMin
    Layout.preferredWidth: marker ? markerSize : vertical ? crossPref : (idle ? sliver : runLength(geoPref, effC.style))
    Layout.preferredHeight: marker ? markerSize : vertical ? (idle ? sliver : runLength(geoPref, effC.style)) : crossPref

    activeFocusOnTab: true
    // Destruído com o mouse em cima (formFactor, reconfiguração): não deixa o hover preso
    Component.onDestruction: if (compactRoot.plasmoidItem) compactRoot.plasmoidItem.setPillHovered(false)
    Keys.onReturnPressed: toggle()
    Keys.onEnterPressed: toggle()
    Keys.onSpacePressed: toggle()
    Keys.onEscapePressed: closePopup()

    Accessible.role: Accessible.Button
    Accessible.name: compactRoot.idle && !compactRoot.marker ? I18n.tr("AI monitor hidden: no CLI running. Activate to open")
        : compactRoot.marker ? I18n.tr("AI monitor: floating Notch active. Activate to open")
        : (compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipMainText : "")
    Accessible.description: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.toolTipSubText : ""
    Accessible.onPressAction: toggle()

    // Pílula sempre escura, independente do tema
    Rectangle {
        id: pill
        visible: !compactRoot.idle && !compactRoot.marker
        anchors.centerIn: parent
        width: Math.min(parent.width, vertical ? compactRoot.geo.w + 2 * pad : compactRoot.runLength(compactRoot.geo, compactRoot.style))
        height: Math.min(parent.height, vertical ? compactRoot.runLength(compactRoot.geo, compactRoot.style) : compactRoot.geo.h + 2 * pad)
        radius: compactRoot.style === "text" || compactRoot.style === "bar"
            ? Math.min(Kirigami.Units.gridUnit * 0.5, Math.min(width, height) / 2) : Math.min(width, height) / 2
        // Ring: sem cápsula comum (cada item tem fundo escuro próprio); a borda segue aparecendo no foco/hover
        color: compactRoot.style === "ring" ? "transparent" : "#15171b"
        border.color: mouseArea.containsMouse || compactRoot.activeFocus ? compactRoot.accent
            : (compactRoot.style === "ring" ? "transparent" : "#2a2d33")
        border.width: 1

        GridLayout {
            anchors.centerIn: parent
            // Último recurso (nem a variante mais compacta cabe): encolhe o conteúdo em vez de vazar da cápsula
            scale: Math.min(1, (pill.width - 2) / Math.max(1, implicitWidth), (pill.height - 2) / Math.max(1, implicitHeight))
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
                    panelStyle: compactRoot.style
                    mode: compactRoot.panel.mode
                    center: compactRoot.eff.center
                    remaining: compactRoot.remaining
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

            // Selos (saúde, atualização, convites): grupo próprio; no Ring leva fundo escuro, já que não há cápsula
            Rectangle {
                id: badgeGroup
                visible: compactRoot.badgeCount > 0
                Layout.alignment: Qt.AlignCenter
                implicitWidth: badgeGrid.implicitWidth + 2 * compactRoot.badgePad
                implicitHeight: badgeGrid.implicitHeight + 2 * compactRoot.badgePad
                radius: Math.min(width, height) / 2
                color: compactRoot.style === "ring" ? "#15171b" : "transparent"

                GridLayout {
                    id: badgeGrid
                    anchors.centerIn: parent
                    columns: compactRoot.vertical ? 1 : 4
                    rowSpacing: compactRoot.gap
                    columnSpacing: compactRoot.gap

                // Selo de saúde (só com Conta Ativa com sessão expirada, sem configurar ou com erro)
                Rectangle {
                    objectName: "badge"
                    id: healthDot
                    visible: compactRoot.health !== ""
                    Layout.alignment: Qt.AlignCenter
                    implicitWidth: Math.max(8, Kirigami.Units.smallSpacing * 1.8)
                    implicitHeight: implicitWidth
                    radius: implicitWidth / 2
                    color: compactRoot.health === "session_expired" ? "#f5a524"
                         : compactRoot.health === "not_configured" ? "#8a9099" : "#ff4d4f"
                    Accessible.name: compactRoot.health === "session_expired" ? I18n.tr("Session expired")
                                   : compactRoot.health === "not_configured" ? I18n.tr("Account not set up") : I18n.tr("Account error")
                }

                // Ponto azul: nova versão de Claude Code, Codex ou Gemini CLI
                Rectangle {
                    objectName: "badge"
                    id: updateDot
                    visible: compactRoot.cliUpdate
                    Layout.alignment: Qt.AlignCenter
                    implicitWidth: Math.max(8, Kirigami.Units.smallSpacing * 1.8)
                    implicitHeight: implicitWidth
                    radius: implicitWidth / 2
                    color: compactRoot.updateColor  // >= 4,5:1 sobre a pílula, qualquer realce (Presets.onPill)
                    Accessible.role: Accessible.Indicator
                    Accessible.name: I18n.tr("New CLI version available")
                    HoverHandler { id: updateDotHover }
                    QQC2.ToolTip.visible: updateDotHover.hovered
                    QQC2.ToolTip.text: I18n.tr("New CLI version available")
                }

                // Selo: nova versão do widget
                Rectangle {
                    objectName: "badge"
                    id: widgetBadge
                    visible: compactRoot.widgetUpdate
                    Layout.alignment: Qt.AlignCenter
                    implicitHeight: Math.max(14, Kirigami.Units.gridUnit * 0.9)
                    implicitWidth: implicitHeight
                    radius: implicitHeight / 2
                    color: compactRoot.updateColor
                    Accessible.role: Accessible.Indicator
                    Accessible.name: I18n.tr("New widget version available")

                    QQC2.Label {
                        anchors.centerIn: parent
                        text: "\u2191"
                        font.bold: true
                        font.pointSize: Kirigami.Theme.smallFont.pointSize * 1.1
                        color: "#15171b"  // cor da pílula sobre o realce clareado: >= 4,5:1
                        textFormat: Text.PlainText
                    }
                }

                // Selo numérico de convites
                Rectangle {
                    objectName: "badge"
                    id: inviteBadge
                    visible: compactRoot.totalInvites > 0
                    Layout.alignment: Qt.AlignCenter
                    implicitHeight: Math.max(14, Kirigami.Units.gridUnit * 0.9)
                    implicitWidth: Math.max(inviteLabel.implicitWidth + 6, implicitHeight)
                    radius: implicitHeight / 2
                    color: "#c24d00"
                    Accessible.name: I18n.trp("%1 invite available", "%1 invites available", compactRoot.totalInvites)

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
        }
    }

    // Marcador no painel com o Notch flutuante ativo: miniatura escura com a cor de realce
    Rectangle {
        objectName: "panelMarker"
        visible: compactRoot.marker
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height) * 0.8
        height: width * 0.5
        radius: height / 2
        color: "#15171b"
        border.width: 1
        border.color: mouseArea.containsMouse || compactRoot.activeFocus ? compactRoot.accent : "#2a2d33"
        Rectangle { anchors.centerIn: parent; width: parent.height * 0.4; height: width; radius: width / 2; color: compactRoot.accent }
    }

    Rectangle {
        visible: compactRoot.idle && !compactRoot.marker
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
        // Na janela flutuante o clique dá o foco à pílula: setas e Home funcionam sem Tab
        onPressed: if (compactRoot.hosted) compactRoot.forceActiveFocus()
        onClicked: compactRoot.plasmoidItem ? compactRoot.plasmoidItem.pillClicked() : compactRoot.toggle()
    }
}
