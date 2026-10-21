import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets
import "I18n.js" as I18n

// Exibicao minima do campo opcional "usage_details" do contrato (v2).
// Linhas sem dado nao aparecem; sem usage_details o componente fica oculto.
ColumnLayout {
    id: detailsRoot

    property var details: null

    spacing: 2
    // Cota por modelo (Gemini): lista recolhivel; modelo sem dado mostra "—", nunca 0%
    property bool modelsExpanded: false
    readonly property var models: (details && details.quota_by_model) ? details.quota_by_model : []

    visible: lines.length > 0 || models.length > 0

    readonly property var lines: {
        var d = detailsRoot.details;
        var out = [];
        if (!d) return out;
        if (d.tokens_by_model && d.tokens_by_model.length > 0)
            out.push(I18n.tr("By model: %1", d.tokens_by_model.slice(0, 3).map(function (m) { return m.model + " " + fmtTokens(m.tokens); }).join(", ")));
        if (d.tokens_by_project && d.tokens_by_project.length > 0)
            out.push(I18n.tr("By project: %1", d.tokens_by_project.slice(0, 3).map(function (p) { return p.project + " " + fmtTokens(p.tokens); }).join(", ")));
        if (d.extra_usage && d.extra_usage.spent !== undefined)
            out.push(d.extra_usage.monthly_limit !== undefined
                ? I18n.tr("Extra usage: $%1 of $%2/month", d.extra_usage.spent.toFixed(2), d.extra_usage.monthly_limit.toFixed(2))
                : I18n.tr("Extra usage: $%1", d.extra_usage.spent.toFixed(2)));
        if (d.credits)
            out.push(d.credits.unlimited ? I18n.tr("Credits: unlimited") : I18n.tr("Credits: %1", d.credits.balance));
        if (d.current_model)
            out.push(I18n.tr("Current model: %1", d.current_model));
        return out;
    }

    function modelPct(p) {
        return (p === null || p === undefined) ? "—" : Math.round(p) + "%";
    }

    function modelReset(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        return "  ·  " + I18n.tr("resets %1", Qt.formatDateTime(d, "dd/MM HH:mm"));
    }

    function fmtTokens(n) {
        if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
        if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
        return String(n);
    }

    QQC2.AbstractButton {
        id: toggle
        visible: detailsRoot.models.length > 0
        Layout.fillWidth: true
        text: I18n.tr("Quota by model (%1)", detailsRoot.models.length)
        checkable: true
        checked: detailsRoot.modelsExpanded
        onToggled: detailsRoot.modelsExpanded = checked
        Accessible.role: Accessible.Button
        Accessible.name: text
        Accessible.checkable: true
        Accessible.checked: checked
        Accessible.expanded: checked
        background: Rectangle {
            radius: 3
            color: Kirigami.Theme.highlightColor
            opacity: toggle.visualFocus ? 0.35 : (toggle.hovered ? 0.18 : 0)
            border.width: toggle.visualFocus ? 2 : 0
            border.color: Kirigami.Theme.highlightColor
        }
        contentItem: QQC2.Label {
            text: (detailsRoot.modelsExpanded ? "▾ " : "▸ ") + toggle.text
            textFormat: Text.PlainText
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
            elide: Text.ElideRight
        }
    }

    Repeater {
        model: detailsRoot.modelsExpanded ? detailsRoot.models : []
        delegate: RowLayout {
            required property var modelData
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing
            QQC2.Label {
                Layout.fillWidth: true
                text: modelData.model + (modelData.window ? " (" + modelData.window + ")" : "")
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Presets.ui.muted
            }
            QQC2.Label {
                text: detailsRoot.modelPct(modelData.usage_percentage) + detailsRoot.modelReset(modelData.reset_time)
                textFormat: Text.PlainText
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Presets.ui.muted
            }
        }
    }

    Repeater {
        model: detailsRoot.lines
        delegate: QQC2.Label {
            required property string modelData
            Layout.fillWidth: true
            text: modelData
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
        }
    }
}
