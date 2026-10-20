import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// Exibicao minima do campo opcional "usage_details" do contrato (v2).
// Linhas sem dado nao aparecem; sem usage_details o componente fica oculto.
ColumnLayout {
    id: detailsRoot

    property var details: null

    spacing: 2
    visible: lines.length > 0

    readonly property var lines: {
        var d = detailsRoot.details;
        var out = [];
        if (!d) return out;
        if (d.tokens_by_model && d.tokens_by_model.length > 0)
            out.push(tr("Por modelo: %1", d.tokens_by_model.slice(0, 3).map(function (m) { return m.model + " " + fmtTokens(m.tokens); }).join(", ")));
        if (d.tokens_by_project && d.tokens_by_project.length > 0)
            out.push(tr("Por projeto: %1", d.tokens_by_project.slice(0, 3).map(function (p) { return p.project + " " + fmtTokens(p.tokens); }).join(", ")));
        if (d.extra_usage && d.extra_usage.spent !== undefined)
            out.push(d.extra_usage.monthly_limit !== undefined
                ? tr("Uso extra: $%1 de $%2/mês", d.extra_usage.spent.toFixed(2), d.extra_usage.monthly_limit.toFixed(2))
                : tr("Uso extra: $%1", d.extra_usage.spent.toFixed(2)));
        if (d.credits)
            out.push(d.credits.unlimited ? tr("Créditos: ilimitados") : tr("Créditos: %1", d.credits.balance));
        if (d.current_model)
            out.push(tr("Modelo atual: %1", d.current_model));
        return out;
    }

    function tr(text, arg1, arg2) {
        if (typeof i18n === "function") {
            if (arg2 !== undefined) return i18n(text, arg1, arg2);
            if (arg1 !== undefined) return i18n(text, arg1);
            return i18n(text);
        }
        var res = text;
        if (arg1 !== undefined) res = res.replace("%1", arg1);
        if (arg2 !== undefined) res = res.replace("%2", arg2);
        return res;
    }

    function fmtTokens(n) {
        if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
        if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
        return String(n);
    }

    Repeater {
        model: detailsRoot.lines
        delegate: QQC2.Label {
            required property string modelData
            Layout.fillWidth: true
            text: modelData
            elide: Text.ElideRight
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            opacity: 0.8
        }
    }
}
