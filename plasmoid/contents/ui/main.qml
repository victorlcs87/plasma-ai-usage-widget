import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtCore

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets
import "NotchModel.js" as NotchModel

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
    // Estado da Sessão ao vivo (--session-state), por id de Conta Claude; vence o campo do contrato
    property var sessionOverlay: ({})
    property var compactModel: NotchModel.buildModel(statusData, { providerOrder: Plasmoid.configuration.providerOrder, hiddenProviders: Plasmoid.configuration.hiddenProviders, showSession: Plasmoid.configuration.sessionState === true, sessionOverlay: sessionOverlay }, safeI18n)
    property string worstHealthStatus: NotchModel.worstHealth(compactModel)
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

    function getSummaryToolTip() {
        if (compactModel.length === 0) {
            return safeI18n("Nenhum provedor visível no painel.");
        }
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

    // Estado da Sessão (ADR-0009): só consulta com a opção ligada; nada toca em hooks aqui
    property bool sessionPolling: false
    property bool autoOpened: false

    function applySessionStates(map) {
        var prev = root.sessionOverlay || {};
        var next = map || {};
        var fired = false;
        for (var id in next) {
            // só transições observadas: a 1ª leitura nunca dispara; terminou = ocupada -> ociosa
            var was = prev[id];
            if (was !== undefined && was !== next[id]
                    && (next[id] === "waiting" || (next[id] === "idle" && was === "busy"))) fired = true;
        }
        root.sessionOverlay = next;
        if (fired) root.sessionAttention();
    }

    // Abre o Notch por 5 s (se estava fechado) e toca o som, só se o usuário ligou cada opção
    function sessionAttention() {
        if (Plasmoid.configuration.sessionAutoOpen !== false && !root.expanded) {
            root.autoOpened = true;
            root.expanded = true;
            sessionCloseTimer.restart();
        }
        if (Plasmoid.configuration.sessionSound === true) {
            soundDataSource.connectSource("sh -c 'command -v canberra-gtk-play >/dev/null 2>&1 && canberra-gtk-play -i complete || paplay /usr/share/sounds/freedesktop/stereo/complete.oga' 2>/dev/null; true");
        }
    }

    Timer {
        id: sessionCloseTimer
        interval: 5000
        onTriggered: {
            var close = root.autoOpened;  // fechado antes pelo usuário: nada a fechar
            root.autoOpened = false;
            if (close) root.expanded = false;
        }
    }

    Plasma5Support.DataSource {
        id: soundDataSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => disconnectSource(sourceName)
    }

    Plasma5Support.DataSource {
        id: sessionDataSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            root.sessionPolling = false;
            try {
                if (data["exit code"] === 0) root.applySessionStates(JSON.parse(data["stdout"]).claude);
            } catch (e) { /* leitura inválida: mantém o último estado */ }
            disconnectSource(sourceName);
        }
    }

    Timer {
        interval: 3000
        repeat: true
        running: Plasmoid.configuration.sessionState === true
        triggeredOnStart: true
        onTriggered: {
            if (root.sessionPolling) return;
            root.sessionPolling = true;
            sessionDataSource.connectSource(root.buildCollectorCommand(root.shellQuote("--session-state")));
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
        if (!root.expanded) root.autoOpened = false;
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
