import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// Historico de Tokens de uma Conta: totais de hoje/semana/mes e grafico de barras.
// Apenas apresenta o campo opcional `token_history` do contrato (calculado no coletor).
ColumnLayout {
    id: root

    property var history: null
    property color barColor: Kirigami.Theme.highlightColor
    // 0 = 30 dias (diario), 1 = 3 meses (semanal), 2 = 12 meses (mensal)
    property int period: 0

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
            color: Kirigami.Theme.disabledTextColor
        }

        QQC2.Label {
            Layout.fillWidth: true
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Kirigami.Theme.disabledTextColor
            elide: Text.ElideRight
            text: root.history
                ? root.tr("Hoje %1", root.compact(root.history.today))
                  + " • " + root.tr("Semana %1", root.compact(root.history.week))
                  + " • " + root.tr("Mês %1", root.compact(root.history.month))
                : ""
        }

        Repeater {
            model: [root.tr("30d"), root.tr("3m"), root.tr("12m")]
            delegate: QQC2.ToolButton {
                required property int index
                required property string modelData
                text: modelData
                checkable: true
                checked: root.period === index
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                onClicked: root.period = index
            }
        }
    }

    Item {
        id: chart
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
                        color: (modelData.tokens || 0) > 0 ? root.barColor : Kirigami.Theme.disabledTextColor
                        opacity: (modelData.tokens || 0) > 0 ? 0.85 : 0.25
                    }

                    MouseArea {
                        id: barMouse
                        anchors.fill: parent
                        hoverEnabled: true
                    }

                    QQC2.ToolTip.visible: barMouse.containsMouse
                    QQC2.ToolTip.text: root.pointLabel(modelData) + ": " + root.compact(modelData.tokens) + " tokens"
                }
            }
        }
    }
}
