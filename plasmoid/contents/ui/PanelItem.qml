import QtQuick
import QtQuick.Layouts
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle

// Um provedor no painel (Conta Ativa no Sistema), no estilo e modo escolhidos. Tamanho = PanelStyle.layout.
// Cor só pelo nível do contrato (Presets.levelColor); a forma do nível vai além da cor em todos os estilos.
Item {
    id: item
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

    readonly property var head: PanelStyle.headline(m)
    readonly property var parts: PanelStyle.parts(panelStyle, mode)
    readonly property color levelColor: Presets.levelColor(head.level, accent)
    readonly property bool known: head.pct >= 0
    readonly property bool shown: active && visible

    // Ring: fundo escuro próprio (sem cápsula comum), sempre legível em tema claro
    Rectangle {
        visible: item.panelStyle === "ring"
        anchors.fill: parent
        radius: Math.min(width, height) / 2
        color: "#15171b"
    }

    GridLayout {
        objectName: "panelGrid"
        anchors.centerIn: parent
        columns: item.vertical ? 1 : 2
        rowSpacing: item.gap
        columnSpacing: item.gap

        Row {
            Layout.alignment: Qt.AlignCenter
            spacing: item.gap

            // Cabeça: inicial (com o Estado da Sessão em volta) + marca de nível
            Row {
                visible: item.parts.head
                anchors.verticalCenter: parent.verticalCenter
                Item {
                    width: item.geo.box
                    height: item.geo.lh
                    SessionMark {
                        width: item.geo.box
                        height: item.geo.box
                        anchors.verticalCenter: parent.verticalCenter
                        sessionState: item.m.sessionState
                        reducedMotion: item.reducedMotion
                        shown: item.shown
                    }
                    Text {
                        anchors.centerIn: parent
                        text: item.m.letter
                        color: "#c9ced6"
                        font.pixelSize: Math.max(7, item.geo.fontPx - 2)
                        font.bold: true
                        textFormat: Text.PlainText
                    }
                }
                Text {
                    objectName: "panelMark"
                    width: item.geo.markW
                    height: item.geo.lh
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                    // O espaço da marca é reservado no tamanho do item (sem reflow ao mudar de nível)
                    visible: PanelStyle.markVisible(item.panelStyle, item.mode, item.head.level)
                    text: PanelStyle.levelMark(item.head.level)
                    color: item.levelColor
                    font.pixelSize: item.geo.fontPx
                    textFormat: Text.PlainText
                }
            }

            DualRing {
                visible: item.parts.graphic && item.panelStyle !== "bar"
                width: item.geo.unit
                height: item.geo.unit
                anchors.verticalCenter: parent.verticalCenter
                outerPct: item.m.outerPct
                innerPct: item.m.innerPct
                outerElapsed: item.m.outerElapsed
                innerElapsed: item.m.innerElapsed
                outerLevel: item.m.outerLevel
                innerLevel: item.m.innerLevel
                outerColor: Presets.levelColor(item.m.outerLevel, item.accent)
                innerColor: Presets.levelColor(item.m.innerLevel, item.accent)
                letter: item.m.letter
                centerMode: item.center
                centerPct: item.known ? String(Math.round(item.head.pct)) : "—"
                sessionState: item.m.sessionState
                active: item.active
                reducedMotion: item.reducedMotion
            }

            LevelBars {
                visible: item.parts.graphic && item.panelStyle === "bar"
                width: 2 * barW + 4
                height: item.geo.unit
                anchors.verticalCenter: parent.verticalCenter
                outerPct: item.m.outerPct
                innerPct: item.m.innerPct
                outerElapsed: item.m.outerElapsed
                innerElapsed: item.m.innerElapsed
                outerLevel: item.m.outerLevel
                innerLevel: item.m.innerLevel
                outerColor: Presets.levelColor(item.m.outerLevel, item.accent)
                innerColor: Presets.levelColor(item.m.innerLevel, item.accent)
            }
        }

        // Porcentagem da janela de destaque; sem dado = "—", dado desatualizado esmaecido
        Text {
            objectName: "panelPct"
            visible: item.parts.pct
            Layout.alignment: Qt.AlignCenter
            Layout.preferredWidth: item.geo.pctW
            Layout.preferredHeight: item.geo.lh
            horizontalAlignment: item.vertical ? Text.AlignHCenter : Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
            text: PanelStyle.pctText(item.head.pct)
            color: item.known ? "#e6e8eb" : "#8a9099"
            opacity: item.known && item.head.level === "" ? 0.6 : 1
            font.pixelSize: item.geo.fontPx
            font.bold: item.head.level === "warning" || item.head.level === "critical"
            fontSizeMode: Text.Fit
            minimumPixelSize: 6
            textFormat: Text.PlainText
        }
    }
}
