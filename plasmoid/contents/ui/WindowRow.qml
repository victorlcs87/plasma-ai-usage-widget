import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle

// Uma janela de uma Conta no popup (NotchModel.windowView): título, nível (forma + palavra + cor), %,
// liberação e previsão. Sem dado: "—" esmaecido, nunca 0%. Cor só pelo nível do contrato.
ColumnLayout {
    id: row

    property var view: ({})
    property bool remaining: false
    property color accent: Kirigami.Theme.highlightColor
    property string summary: ""

    readonly property color levelColor: Presets.levelColor(view.level || "", accent)
    readonly property bool flagged: view.level === "warning" || view.level === "critical"

    spacing: 1
    opacity: view.dim ? 0.55 : 1
    Accessible.role: Accessible.StaticText
    Accessible.name: summary

    function tr(text) { return typeof i18n === "function" ? i18n(text) : text; }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        QQC2.Label {
            Accessible.ignored: true
            Layout.fillWidth: true
            text: row.view.title || ""
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
        }
        QQC2.Label {
            objectName: "levelWord"
            Accessible.ignored: true
            visible: row.flagged
            text: row.view.level === "critical" ? row.tr("Crítico") : row.tr("Atenção")
            textFormat: Text.PlainText
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            font.bold: true
            color: row.levelColor
        }
        QQC2.Label {  // forma do nível: normal ●, atenção ▲, crítico ■, sem nível ○
            objectName: "levelMark"
            Accessible.ignored: true
            text: PanelStyle.levelMark(row.view.level || "")
            textFormat: Text.PlainText
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: row.levelColor
        }
        QQC2.Label {
            objectName: "pct"
            Accessible.ignored: true
            text: row.view.text || "—"
            textFormat: Text.PlainText
            font.bold: true
            font.pointSize: Kirigami.Theme.defaultFont.pointSize
            color: row.view.known ? row.levelColor : Presets.ui.muted
        }
        QQC2.Label {
            Accessible.ignored: true
            visible: row.view.known === true
            text: row.remaining ? row.tr("restante") : row.tr("usado")
            textFormat: Text.PlainText
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
        }
    }

    QQC2.Label {
        objectName: "reset"
        Accessible.ignored: true
        Layout.fillWidth: true
        visible: text.length > 0
        text: [row.view.tokens, row.view.reset].filter(function (x) { return x; }).join(" • ")
        textFormat: Text.PlainText
        elide: Text.ElideRight
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: Presets.ui.muted
        HoverHandler { id: resetHover }
        QQC2.ToolTip.visible: resetHover.hovered && Boolean(row.view.resetFull)
        QQC2.ToolTip.text: row.view.resetFull || ""
    }

    QQC2.Label {
        objectName: "forecast"
        Accessible.ignored: true
        Layout.fillWidth: true
        visible: text.length > 0
        text: row.view.forecast ? row.view.forecast.text : ""
        textFormat: Text.PlainText
        elide: Text.ElideRight
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        font.bold: row.view.forecast ? row.view.forecast.warn : false
        color: row.view.forecast && row.view.forecast.warn ? Presets.ui.fg : Presets.ui.muted
    }
}
