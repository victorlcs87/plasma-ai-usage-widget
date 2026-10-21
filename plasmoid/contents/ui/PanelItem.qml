import QtQuick
import QtQuick.Layouts
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle
import "ViewPrefs.js" as ViewPrefs

// Um provedor no painel (Conta Ativa no Sistema), no estilo e modo escolhidos. Tamanho = PanelStyle.layout.
// Cor só pelo nível do contrato (Presets.levelColor); a forma do nível vai além da cor em todos os estilos.
Item {
    id: pi
    objectName: "panelItem"

    property var m: ({})                // entrada de NotchModel.buildModel
    property string panelStyle: "pill"  // pill | ring | text | bar
    property string mode: "ring"        // ring | ringpct | pct
    property string center: "logo"      // centro do anel: logo | pct | logopct
    property bool vertical: false
    property var geo: ({ unit: 22, fontPx: 11, lh: 14, box: 13, markW: 11, pctW: 30, ip: 0 })
    property int gap: 4
    property color accent: "#3daee9"
    property bool active: true
    property bool reducedMotion: false
    property bool remaining: false      // preferência usado/restante: o % e os arcos mostram o que resta

    readonly property var head: PanelStyle.headline(m)
    readonly property var parts: PanelStyle.parts(panelStyle, mode)
    readonly property color levelColor: Presets.levelTextColor(head.level, accent)
    readonly property bool known: head.pct >= 0
    // Sem nível com dado = obsoleto: esmaecido
    readonly property bool dim: known && head.level === ""
    readonly property bool shown: active && visible

    // Ring: fundo escuro próprio (sem cápsula comum), sempre legível em tema claro
    Rectangle {
        visible: pi.panelStyle === "ring"
        anchors.fill: parent
        radius: Math.min(width, height) / 2
        color: Presets.ui.panel
    }

    GridLayout {
        objectName: "panelGrid"
        anchors.centerIn: parent
        columns: pi.vertical ? 1 : 2
        rowSpacing: pi.gap
        columnSpacing: pi.gap

        Row {
            Layout.alignment: Qt.AlignCenter
            spacing: pi.gap

            // Cabeça: inicial (com o Estado da Sessão em volta) + marca de nível
            Row {
                visible: pi.parts.head
                anchors.verticalCenter: parent.verticalCenter
                Item {
                    width: pi.geo.box
                    height: pi.geo.lh
                    SessionMark {
                        width: pi.geo.box
                        height: pi.geo.box
                        anchors.verticalCenter: parent.verticalCenter
                        sessionState: pi.m.sessionState
                        reducedMotion: pi.reducedMotion
                        shown: pi.shown
                    }
                    Text {
                        Accessible.ignored: true
                        anchors.centerIn: parent
                        text: pi.m.letter
                        color: Presets.ui.letter
                        font.pixelSize: Math.max(7, pi.geo.fontPx - 2)
                        font.bold: true
                        textFormat: Text.PlainText
                    }
                }
                Text {
                    objectName: "panelMark"
                    Accessible.ignored: true
                    width: pi.geo.markW
                    height: pi.geo.lh
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                    // O espaço da marca é reservado no tamanho do item (sem reflow ao mudar de nível)
                    visible: PanelStyle.markVisible(pi.panelStyle, pi.mode, pi.head.level)
                    text: PanelStyle.levelMark(pi.head.level)
                    color: pi.levelColor
                    font.pixelSize: pi.geo.fontPx
                    textFormat: Text.PlainText
                }
            }

            // Só o gráfico do estilo é instanciado (anéis ou barras)
            Loader {
                active: pi.parts.graphic && pi.panelStyle !== "bar"
                visible: active
                width: pi.geo.unit
                height: pi.geo.unit
                anchors.verticalCenter: parent.verticalCenter
                sourceComponent: DualRing {
                    outerPct: ViewPrefs.shownPct(pi.m.outerPct, pi.remaining)
                    innerPct: ViewPrefs.shownPct(pi.m.innerPct, pi.remaining)
                    outerElapsed: pi.m.outerElapsed
                    innerElapsed: pi.m.innerElapsed
                    outerLevel: pi.m.outerLevel
                    innerLevel: pi.m.innerLevel
                    outerColor: Presets.levelColor(pi.m.outerLevel, pi.accent)
                    innerColor: Presets.levelColor(pi.m.innerLevel, pi.accent)
                    letter: pi.m.letter
                    centerMode: pi.center
                    centerPct: pi.known ? String(ViewPrefs.shownPct(pi.head.pct, pi.remaining)) : "\u2014"
                    centerDim: pi.dim
                    sessionState: pi.m.sessionState
                    active: pi.active
                    reducedMotion: pi.reducedMotion
                }
            }

            Loader {
                active: pi.parts.graphic && pi.panelStyle === "bar"
                visible: active
                width: PanelStyle.barsWidth(pi.geo.unit)
                height: pi.geo.unit
                anchors.verticalCenter: parent.verticalCenter
                sourceComponent: LevelBars {
                    outerPct: ViewPrefs.shownPct(pi.m.outerPct, pi.remaining)
                    innerPct: ViewPrefs.shownPct(pi.m.innerPct, pi.remaining)
                    outerElapsed: pi.m.outerElapsed
                    innerElapsed: pi.m.innerElapsed
                    outerLevel: pi.m.outerLevel
                    innerLevel: pi.m.innerLevel
                    outerColor: Presets.levelColor(pi.m.outerLevel, pi.accent)
                    innerColor: Presets.levelColor(pi.m.innerLevel, pi.accent)
                }
            }
        }

        // Porcentagem da janela de destaque; sem dado = "—", dado desatualizado esmaecido
        Text {
            objectName: "panelPct"
            Accessible.ignored: true
            visible: pi.parts.pct
            Layout.alignment: Qt.AlignCenter
            Layout.preferredWidth: pi.geo.pctW
            Layout.preferredHeight: pi.geo.lh
            horizontalAlignment: pi.vertical ? Text.AlignHCenter : Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
            text: PanelStyle.pctText(pi.head.pct, pi.remaining)
            color: pi.known ? Presets.ui.fg : Presets.neutral
            opacity: pi.dim ? 0.6 : 1
            font.pixelSize: pi.geo.fontPx
            font.bold: pi.head.level === "warning" || pi.head.level === "critical"
            fontSizeMode: Text.Fit
            minimumPixelSize: 6
            textFormat: Text.PlainText
        }
    }
}
