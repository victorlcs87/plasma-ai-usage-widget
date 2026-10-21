import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets

// Historico de Tokens de uma Conta: totais de hoje/semana/mes e grafico de barras.
// Apenas apresenta o campo opcional `token_history` do contrato (calculado no coletor).
ColumnLayout {
    id: root

    property var history: null
    property color barColor: Kirigami.Theme.highlightColor
    // 0 = 30 dias (diario), 1 = 3 meses (semanal), 2 = 12 meses (mensal)
    property int period: 0
    // Recolhido: só o resumo Hoje/Semana/Mês; gráfico e períodos aparecem expandidos
    property bool summaryOnly: false
    property string owner: ""  // Conta dona (nomes acessíveis dos botões de período não se repetem por cartão)

    readonly property var series: {
        if (!history) return [];
        var s = period === 1 ? history.weekly_3m : (period === 2 ? history.monthly_12m : history.daily_30d);
        return s || [];
    }
    readonly property real maxTokens: {
        var m = 0;
        for (var i = 0; i < series.length; i++) m = Math.max(m, series[i].tokens || 0);
        return m;
    }

    visible: Boolean(history)
    spacing: Kirigami.Units.smallSpacing

    function tr(text, arg1) {
        var out = (typeof i18n === "function") ? i18n(text, arg1) : text;
        return arg1 === undefined ? out : out.replace("%1", arg1);
    }

    function compact(n) {
        n = Number(n) || 0;
        if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
        if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
        if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
        return String(n);
    }

    readonly property var periodNames: [tr("30 dias"), tr("3 meses"), tr("12 meses")]

    function pointLabel(p) {
        return p.date || p.week_start || p.month || "";
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            source: "office-chart-bar"
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
            color: Presets.ui.muted
        }

        QQC2.Label {
            Layout.fillWidth: true
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
            elide: Text.ElideRight
            textFormat: Text.PlainText
            text: root.history
                ? root.tr("Hoje %1", root.compact(root.history.today))
                  + " • " + root.tr("Semana %1", root.compact(root.history.week))
                  + " • " + root.tr("Mês %1", root.compact(root.history.month))
                + (root.history.estimated ? " • " + root.tr("estimado") : "")
                : ""
        }

        Repeater {
            model: root.summaryOnly ? [] : [root.tr("30d"), root.tr("3m"), root.tr("12m")]
            delegate: NotchButton {
                required property int index
                required property string modelData
                text: modelData
                visible: !root.summaryOnly
                accessibleName: root.owner ? root.periodNames[index] + ", " + root.owner : root.periodNames[index]
                hint: root.periodNames[index]
                checkable: true
                checked: root.period === index
                accent: root.barColor
                onClicked: root.period = index
            }
        }
    }

    Item {
        id: chart
        visible: !root.summaryOnly
        // Resumo para tecnologias assistivas: as barras são só visuais
        Accessible.role: Accessible.Chart
        Accessible.name: root.tr("Histórico de tokens, %1", root.periodNames[root.period])
        Accessible.description: root.series.length === 0 ? root.tr("Sem dados") : root.tr("Maior valor: %1", root.compact(root.maxTokens))
        Layout.fillWidth: true
        implicitHeight: Kirigami.Units.gridUnit * 2

        Row {
            anchors.fill: parent
            spacing: 1

            Repeater {
                model: root.series
                delegate: Item {
                    required property var modelData
                    width: root.series.length > 0 ? (chart.width - (root.series.length - 1)) / root.series.length : 0
                    height: chart.height

                    Rectangle {
                        anchors.bottom: parent.bottom
                        width: parent.width
                        radius: 1
                        height: root.maxTokens > 0 ? Math.max(1, parent.height * (modelData.tokens || 0) / root.maxTokens) : 1
                        color: (modelData.tokens || 0) > 0 ? root.barColor : Presets.ui.muted
                        opacity: (modelData.tokens || 0) > 0 ? 0.85 : 0.25
                    }

                    MouseArea {
                        id: barMouse
                        anchors.fill: parent
                        hoverEnabled: true
                    }

                    PlainTip { visible: barMouse.containsMouse; text: root.pointLabel(modelData) + ": " + root.compact(modelData.tokens) + " tokens" }
                }
            }
        }
    }
}
