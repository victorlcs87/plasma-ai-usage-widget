import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtCore

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    readonly property bool inPanel: Plasmoid.formFactor !== PlasmaCore.Types.Planar

    Plasmoid.backgroundHints: root.inPanel
        ? (PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground)
        : PlasmaCore.Types.DefaultBackground

    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar ? fullRepresentation : null

    Plasmoid.icon: "view-split-left-right"
    Plasmoid.title: safeI18n("Monitor de Uso de IA")
    toolTipMainText: Plasmoid.title || ""
    toolTipSubText: getSummaryToolTip() || ""

    property var statusData: null
    property string lastError: ""
    property bool isLoading: false
    property string lastUpdatedFormatted: formatLastUpdated(statusData?.last_updated)
    property int totalInvites: calculateTotalInvites()
    property double maxUsagePercent: calculateMaxUsage()

    function safeI18n(text, arg1, arg2) {
        if (!text) return "";
        if (typeof i18n === "function") {
            if (arg2 !== undefined) return i18n(text, arg1, arg2);
            if (arg1 !== undefined) return i18n(text, arg1);
            return i18n(text);
        }
        var res = text || "";
        if (arg1 !== undefined) res = res.replace("%1", arg1);
        if (arg2 !== undefined) res = res.replace("%2", arg2);
        return res;
    }

    function formatLastUpdated(isoStr) {
        if (!isoStr) return "";
        try {
            var date = new Date(isoStr);
            if (isNaN(date.getTime())) return "";
            var hours = date.getHours();
            var minutes = date.getMinutes();
            var timeStr = (hours < 10 ? "0" : "") + hours + ":" + (minutes < 10 ? "0" : "") + minutes;
            return safeI18n("Atualizado às %1", timeStr);
        } catch (e) {
            return "";
        }
    }

    function calculateTotalInvites() {
        if (!statusData || !statusData.agents) return 0;
        var total = 0;
        for (var agentKey in statusData.agents) {
            if (!statusData.agents.hasOwnProperty(agentKey)) continue;
            var accounts = statusData.agents[agentKey].accounts || [];
            for (var i = 0; i < accounts.length; i++) {
                var inv = accounts[i].free_trial_invites;
                if (inv && inv.available_count > 0) {
                    total += inv.available_count;
                }
            }
        }
        return total;
    }

    function calculateMaxUsage() {
        if (!statusData || !statusData.agents) return 0.0;
        var maxPct = 0.0;
        for (var agentKey in statusData.agents) {
            if (!statusData.agents.hasOwnProperty(agentKey)) continue;
            var accounts = statusData.agents[agentKey].accounts || [];
            for (var i = 0; i < accounts.length; i++) {
                var nw = accounts[i].native_window;
                if (nw && nw.usage_percentage !== undefined && nw.usage_percentage !== null) {
                    if (nw.usage_percentage > maxPct) {
                        maxPct = nw.usage_percentage;
                    }
                }
            }
        }
        return maxPct;
    }

    function getSummaryToolTip() {
        if (!statusData || !statusData.agents) {
            return safeI18n("Nenhum dado coletado ainda.");
        }
        var lines = [];
        var agents = statusData.agents;
        for (var key in agents) {
            if (!agents.hasOwnProperty(key)) continue;
            var ag = agents[key];
            var accs = ag.accounts || [];
            if (accs.length > 0) {
                var firstAcc = accs[0];
                var pct = firstAcc.native_window?.usage_percentage;
                var pctStr = (pct !== undefined && pct !== null) ? pct.toFixed(0) + "%" : "-";
                lines.push(ag.name + ": " + pctStr);
            }
        }
        if (totalInvites > 0) {
            lines.push(safeI18n("%1 convites disponíveis", totalInvites));
        }
        return lines.join(" • ");
    }

    // Leitor assíncrono via DataSource do KDE Plasma
    Plasma5Support.DataSource {
        id: statusDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            root.isLoading = false;
            var exitCode = data["exit code"];
            var stdout = data["stdout"];
            var stderr = data["stderr"];

            if (exitCode === 0 && stdout && stdout.trim().length > 0) {
                try {
                    var parsed = JSON.parse(stdout);
                    root.statusData = parsed;
                    root.lastError = "";
                } catch (e) {
                    root.lastError = safeI18n("Erro ao ler JSON de status: %1", e.message);
                }
            } else {
                if (exitCode !== 0) {
                    root.lastError = safeI18n("Cache de status não encontrado. Execute o coletor.");
                }
            }
            disconnectSource(sourceName);
        }
    }

    function loadStatus() {
        root.isLoading = true;
        var cacheLoc = StandardPaths.writableLocation(StandardPaths.GenericCacheLocation);
        var cachePath = (typeof cacheLoc === "string" ? cacheLoc : cacheLoc.toString()).replace(/^file:\/\//, "");
        var statusFilePath = cachePath + "/plasma-ai-usage/status.json";
        var cmd = "cat \"" + statusFilePath + "\" 2>/dev/null";
        statusDataSource.connectSource(cmd);
    }

    // Timer para recarregar periodicamente a cada 30 segundos (somente quando ativo/visível)
    Timer {
        id: autoReloadTimer
        interval: 30000
        repeat: true
        running: root.expanded || !root.inPanel
        onTriggered: root.loadStatus()
    }

    onExpandedChanged: {
        if (root.expanded) {
            root.loadStatus();
        }
    }

    Component.onCompleted: {
        root.loadStatus();
    }

    compactRepresentation: CompactRepresentation {
        plasmoidItem: root
    }

    fullRepresentation: FullRepresentation {
        plasmoidItem: root
    }
}
