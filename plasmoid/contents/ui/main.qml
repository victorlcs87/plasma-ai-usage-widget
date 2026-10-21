import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtCore

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets

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
    property bool isRefreshing: false
    property string lastUpdatedFormatted: formatLastUpdated(statusData?.last_updated)
    property int totalInvites: calculateTotalInvites()
    // Notch compacto: provedores visíveis, na ordem escolhida, com a Conta Ativa no Sistema de cada um
    property var compactModel: buildCompactModel()
    property string worstHealthStatus: worstHealth()
    readonly property color accentColor: Presets.accentColor(Plasmoid.configuration.accentPreset, Kirigami.Theme.highlightColor)

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

    function visibleProviders() {
        var hidden = String(Plasmoid.configuration.hiddenProviders || "").split(",");
        return Presets.normalizeOrder(Plasmoid.configuration.providerOrder).filter(function (k) {
            return hidden.indexOf(k) === -1;
        });
    }

    // Conta Ativa no Sistema; sem nenhuma marcada, a primeira do provedor
    function activeAccount(agent) {
        var accs = (agent && agent.accounts) || [];
        for (var i = 0; i < accs.length; i++) {
            if (accs[i].isActive === true || accs[i].is_active === true) return accs[i];
        }
        return accs.length > 0 ? accs[0] : null;
    }

    // Percentual da janela, ou -1 (desconhecido): sem dado, nulo ou obsoleto com liberação já passada
    function windowPct(acc, win, resetKey) {
        if (!acc || !win || acc.no_data === true) return -1;
        var p = win.usage_percentage;
        if (p === undefined || p === null) return -1;
        var t = win[resetKey] ? Date.parse(win[resetKey]) : NaN;
        if (acc.stale === true && !isNaN(t) && t <= Date.now()) return -1;
        return p;
    }

    // Nível do contrato; ausente, obsoleto ou sem dado = "" (cor neutra)
    function windowLevel(acc, win, pct) {
        if (!acc || !win || pct < 0 || acc.stale === true || acc.no_data === true) return "";
        return win.alert_level || "";
    }

    function windowElapsed(acc, win, pct) {
        if (pct < 0 || acc.stale === true || !(win.window_seconds > 0)) return -1;
        var e = win.elapsed_fraction;
        return (e === undefined || e === null) ? -1 : e;
    }

    function levelWord(level) {
        if (level === "critical") return safeI18n("crítico");
        if (level === "warning") return safeI18n("atenção");
        if (level === "normal") return safeI18n("normal");
        return safeI18n("sem nível");
    }

    function pctWord(pct) {
        return pct < 0 ? "-" : Math.round(pct) + "%";
    }

    function buildCompactModel() {
        var agents = (statusData && statusData.agents) || {};
        return visibleProviders().map(function (key) {
            var info = Presets.providerInfo(key);
            var ag = agents[key];
            var acc = activeAccount(ag);
            var nw = acc ? acc.native_window : null;
            var ww = acc ? acc.weekly_window : null;
            var inner = windowPct(acc, nw, "release_time");
            var outer = windowPct(acc, ww, "cycle_reset_time");
            var il = windowLevel(acc, nw, inner);
            var ol = windowLevel(acc, ww, outer);
            var tail = !acc ? safeI18n("sem dados") : (acc.stale === true ? safeI18n("dados desatualizados") : "");
            if (acc && acc.limit_changes && acc.limit_changes.length > 0) {
                tail += (tail ? ", " : "") + safeI18n("limites mudaram");
            }
            return {
                provider: key,
                name: (ag && ag.name) || info.name,
                letter: info.letter,
                innerPct: inner,
                outerPct: outer,
                innerLevel: il,
                outerLevel: ol,
                innerElapsed: acc ? windowElapsed(acc, nw, inner) : -1,
                outerElapsed: acc ? windowElapsed(acc, ww, outer) : -1,
                description: safeI18n("Janela nativa %1 (%2)", pctWord(inner), levelWord(il))
                    + ", " + safeI18n("semanal %1 (%2)", pctWord(outer), levelWord(ol))
                    + (tail ? ", " + tail : "")
            };
        });
    }

    // Saúde da pior Conta Ativa visível: "" quando tudo válido ou sem dados
    function worstHealth() {
        var agents = (statusData && statusData.agents) || {};
        var worst = "";
        visibleProviders().forEach(function (key) {
            var acc = activeAccount(agents[key]);
            var st = acc && acc.health ? acc.health.status : "";
            if (!st || st === "valid") return;
            if (st === "session_expired" || worst === "") worst = st;
        });
        return worst;
    }

    function getSummaryToolTip() {
        if (!statusData || !statusData.agents) {
            return safeI18n("Nenhum dado coletado ainda.");
        }
        var lines = compactModel.map(function (m) { return m.name + ": " + m.description; });
        if (totalInvites > 0) {
            lines.push(safeI18n("%1 convites disponíveis", totalInvites));
        }
        return lines.join("\n");
    }

    function shellQuote(str) {
        if (str === null || str === undefined) return "''";
        return "'" + String(str).replace(/'/g, "'\\''") + "'";
    }

    function buildCollectorCommand(quotedArgs) {
        return "bash -c 'if command -v ai-usage-collector >/dev/null 2>&1; then ai-usage-collector \"$@\"; " +
               "elif [ -x \"$HOME/.local/bin/ai-usage-collector\" ]; then \"$HOME/.local/bin/ai-usage-collector\" \"$@\"; " +
               "elif [ -x \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" ]; then \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" \"$@\"; " +
               "else python3 -m ai_usage_collector \"$@\"; fi' _ " + (quotedArgs || "");
    }

    // Executor assíncrono de comandos do coletor (refresh / remoção)
    Plasma5Support.DataSource {
        id: collectorDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            root.isRefreshing = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                root.lastError = "";
                root.loadStatus();
            } else {
                var errMsg = stderr || stdout || safeI18n("Código de saída %1", exitCode);
                root.lastError = safeI18n("Erro ao executar coletor: %1", errMsg);
            }
            disconnectSource(sourceName);
            root.runPendingRemoval();
        }
    }

    property var pendingRemovals: []

    function runPendingRemoval() {
        var next = root.pendingRemovals.shift();
        if (next) root.removeAccount(next[0], next[1]);
    }

    // Segurança: coletor travado não pode bloquear as próximas execuções para sempre
    Timer {
        id: refreshWatchdog
        interval: 120000
        running: root.isRefreshing
        onTriggered: {
            var stuck = collectorDataSource.connectedSources.slice();
            for (var i = 0; i < stuck.length; i++) collectorDataSource.disconnectSource(stuck[i]);
            root.isRefreshing = false;
            root.lastError = root.safeI18n("O coletor não respondeu em 120 s; nova tentativa no próximo ciclo.");
            root.runPendingRemoval();
        }
    }

    // Intervalo de Atualização por provedor (ADR-0007); o coletor respeita pausas (429) por conta própria
    readonly property var providers: ["claude", "codex", "gemini"]
    property var lastProviderRefresh: ({})

    function providerInterval(provider) {
        var key = "refreshInterval" + provider.charAt(0).toUpperCase() + provider.slice(1);
        return Math.max(60, Plasmoid.configuration[key] || 300);
    }

    function runCollectorRefresh(dueProviders) {
        if (root.isRefreshing) return;
        var now = Date.now();
        var targets = dueProviders || root.providers;
        for (var i = 0; i < targets.length; i++) root.lastProviderRefresh[targets[i]] = now;

        var args = shellQuote("--refresh");
        if (dueProviders) args += " " + shellQuote("--provider") + " " + shellQuote(dueProviders.join(","));
        for (var j = 0; j < root.providers.length; j++) {
            var p = root.providers[j];
            args += " " + shellQuote("--refresh-interval") + " " + shellQuote(p + "=" + providerInterval(p));
        }
        root.isRefreshing = true;
        root.lastError = "";
        collectorDataSource.connectSource(buildCollectorCommand(args));
    }

    // "Atualizar agora": ignora o intervalo de todos os provedores
    function refreshCollector() {
        runCollectorRefresh(null);
    }

    Timer {
        id: providerRefreshScheduler
        interval: 15000
        repeat: true
        running: true
        onTriggered: {
            var now = Date.now();
            var due = [];
            for (var i = 0; i < root.providers.length; i++) {
                var p = root.providers[i];
                var last = root.lastProviderRefresh[p];
                if (last === undefined || now - last >= root.providerInterval(p) * 1000) due.push(p);
            }
            if (due.length > 0) root.runCollectorRefresh(due);
        }
    }

    function removeAccount(provider, accountId) {
        if (!provider || !accountId) return;
        var provClean = String(provider).toLowerCase().trim();
        if (["claude", "codex", "gemini"].indexOf(provClean) === -1) return;

        // Coletor já em execução: enfileira a remoção para quando ele terminar
        if (root.isRefreshing) {
            root.pendingRemovals.push([provClean, accountId]);
            return;
        }
        root.isRefreshing = true;
        root.lastError = "";
        var safeArgs = shellQuote("--remove-account") + " " + shellQuote(provClean) + " " + shellQuote(accountId);
        var cmd = buildCollectorCommand(safeArgs);
        collectorDataSource.connectSource(cmd);
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
        var cmd = "cat " + shellQuote(statusFilePath) + " 2>/dev/null";
        statusDataSource.connectSource(cmd);
    }

    onExpandedChanged: {
        if (root.expanded && (Plasmoid.configuration.autoRefreshOnExpand !== false)) {
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
