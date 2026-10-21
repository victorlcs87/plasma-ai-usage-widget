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
import "ViewPrefs.js" as ViewPrefs
import "I18n.js" as I18n

PlasmoidItem {
    id: root

    readonly property bool inPanel: Plasmoid.formFactor !== PlasmaCore.Types.Planar

    Plasmoid.backgroundHints: root.inPanel
        ? (PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground)
        : PlasmaCore.Types.DefaultBackground

    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar ? fullRepresentation : null

    Plasmoid.icon: "view-split-left-right"
    Plasmoid.title: I18n.tr("AI Usage Monitor")
    toolTipMainText: Plasmoid.title || ""
    toolTipSubText: getSummaryToolTip() || ""
    toolTipTextFormat: Text.PlainText

    // Abrir por hover (~300 ms) e fixar com clique (ticket 34); sem hover, só o clique
    readonly property bool hoverOpen: Plasmoid.configuration.hoverOpen !== false
    property bool pinned: false
    property bool pillHovered: false
    property bool popupHovered: false
    property double now: Date.now()
    // Só fecha por hover o popup que o hover abriu (ou que foi solto); atalho/ação externa nunca
    property bool openedByHover: false
    // Com o mouse na pílula o press tira o foco do popup: não pode fechá-lo antes do clique fixar
    hideOnWindowDeactivate: !pinned && !pillHovered

    property var statusData: null
    property string lastError: ""
    property bool isLoading: false
    property bool isRefreshing: false
    property string lastUpdatedFormatted: formatLastUpdated(statusData?.last_updated)
    property int totalInvites: calculateTotalInvites()
    // Notch compacto: provedores visíveis, na ordem escolhida, com a Conta Ativa no Sistema de cada um
    // Estado da Sessão ao vivo (--session-state), por id de Conta Claude; vence o campo do contrato
    property var sessionOverlay: ({})
    // Preferências de exibição (usado/restante, contagem/data): valem no painel, na dica e no popup
    readonly property var viewPrefs: ViewPrefs.config(Plasmoid.configuration)
    property var compactModel: NotchModel.buildModel(statusData, { providerOrder: Plasmoid.configuration.providerOrder, hiddenProviders: Plasmoid.configuration.hiddenProviders, remaining: viewPrefs.remaining, idleProviders: root.confirmedIdle, showSession: Plasmoid.configuration.sessionState === true, sessionOverlay: sessionOverlay }, I18n.tr, root.nowMs)
    property var updateInfo: NotchModel.updateSummary(statusData, I18n.tr)
    property string worstHealthStatus: NotchModel.worstHealth(compactModel)
    // Relógio observável para a frescura de `running` (Date.now() não dispara reavaliação): atualizado pelo
    // Timer de 15 s e a cada status lido, para uma leitura velha deixar de esconder mesmo sem status novo.
    property double nowMs: Date.now()
    property int idleDelayMs: 20000
    // Opção "ocultar sem o processo da CLI" (modo widget; desligada por padrão). Recuperação: nunca oculta
    // com o popup aberto, o mouse sobre o widget ou a configuração aberta; no painel resta uma fatia clicável
    // (botão direito abre "Configurar"), e na bandeja o status Passivo mantém o widget nos itens ocultos.
    // Histerese: some só depois de `idleDelayMs` ininterruptos (sem tremor); reaparece na hora.
    readonly property bool idleWanted: NotchModel.widgetIdle(statusData, { providerOrder: Plasmoid.configuration.providerOrder, hiddenProviders: Plasmoid.configuration.hiddenProviders }, root.nowMs)
        && !root.expanded && !Plasmoid.userConfiguring && !root.pillHovered && !root.pinned && !root.popupHovered
    property bool idleHidden: false
    onIdleWantedChanged: {
        if (idleWanted) idleDelay.restart();
        else { idleDelay.stop(); idleHidden = false; }
    }
    // Modo "provider": o provedor só some após `idleDelayMs` parado (sem reflow a cada oscilação); volta na hora
    // string (não array): recalcular sem mudança não reinicia o atraso
    readonly property string rawIdle: NotchModel.idleProviders(statusData, { providerOrder: Plasmoid.configuration.providerOrder, hiddenProviders: Plasmoid.configuration.hiddenProviders }, root.nowMs).join(",")
    property var confirmedIdle: []
    onRawIdleChanged: {
        var raw = rawIdle === "" ? [] : rawIdle.split(",");
        confirmedIdle = confirmedIdle.filter(function (k) { return raw.indexOf(k) >= 0; });
        if (raw.length > confirmedIdle.length) providerIdleDelay.restart(); else providerIdleDelay.stop();
    }
    Timer {
        id: providerIdleDelay
        interval: root.idleDelayMs
        onTriggered: root.confirmedIdle = root.rawIdle === "" ? [] : root.rawIdle.split(",")
    }
    Timer {
        id: idleDelay
        interval: root.idleDelayMs
        onTriggered: root.idleHidden = root.idleWanted
    }
    Plasmoid.status: root.idleHidden ? PlasmaCore.Types.PassiveStatus : PlasmaCore.Types.ActiveStatus
    readonly property color accentColor: Presets.accentColor(Plasmoid.configuration.accentPreset, Kirigami.Theme.highlightColor)

    function formatLastUpdated(isoStr) {
        if (!isoStr) return "";
        try {
            var date = new Date(isoStr);
            if (isNaN(date.getTime())) return "";
            var hours = date.getHours();
            var minutes = date.getMinutes();
            var timeStr = (hours < 10 ? "0" : "") + hours + ":" + (minutes < 10 ? "0" : "") + minutes;
            return I18n.tr("Updated at %1", timeStr);
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
            return I18n.tr("No provider visible in the panel.");
        }
        if (!statusData || !statusData.agents) {
            return I18n.tr("No data collected yet.");
        }
        var lines = [NotchModel.tooltipText(statusData, { providerOrder: Plasmoid.configuration.providerOrder, hiddenProviders: Plasmoid.configuration.hiddenProviders, remaining: viewPrefs.remaining, date: viewPrefs.date }, I18n.tr, now)];
        if (totalInvites > 0) {
            lines.push(I18n.trp("%1 invite available", "%1 invites available", totalInvites));
        }
        if (sessionFailed && Plasmoid.configuration.sessionState === true) {
            lines.push(I18n.tr("Session state unavailable: reinstall the collector package (pip install -e .)"));
        }
        return lines.join("\n");
    }

    function setPillHovered(h) {
        pillHovered = h;
        if (h) {
            now = Date.now();
            if (hoverOpen && !expanded) hoverOpenTimer.restart();
        } else {
            hoverOpenTimer.stop();
            scheduleHoverClose();
        }
    }

    function scheduleHoverClose() {
        if (hoverOpen && expanded && openedByHover && !pinned && !pillHovered && !popupHovered) hoverCloseTimer.restart();
    }

    function setPopupHovered(h) {
        popupHovered = h;
        if (h) hoverCloseTimer.stop();
        else scheduleHoverClose();
    }

    // Clique: fecha/abre como antes; com hover ligado, clicar no popup aberto por hover o fixa, e de novo o solta
    function pillClicked() {
        hoverOpenTimer.stop();
        if (!hoverOpen) { expanded = !expanded; return; }
        if (!expanded) { pinned = true; expanded = true; }
        else {
            pinned = !pinned;
            if (!pinned) { openedByHover = true; scheduleHoverClose(); }  // solto: volta a fechar ao sair
        }
    }

    function closePopup() {
        pinned = false;
        expanded = false;
    }

    // Abre depois de ~300 ms com o mouse sobre a pílula
    Timer {
        id: hoverOpenTimer
        interval: 300
        onTriggered: if (root.hoverOpen && root.pillHovered && !root.expanded) { root.openedByHover = true; root.expanded = true; }
    }

    // Atraso curto de saída: o mouse transita pílula -> popup sem piscar
    Timer {
        id: hoverCloseTimer
        interval: 250
        onTriggered: if (root.hoverOpen && root.openedByHover && !root.pinned && !root.pillHovered && !root.popupHovered) root.expanded = false
    }

    // Contagem regressiva da dica: só enquanto o mouse está na pílula com o popup fechado
    Timer {
        id: tooltipTick
        interval: 1000
        repeat: true
        running: root.pillHovered && !root.expanded
        onTriggered: root.now = Date.now()
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

    // Caminho leve do Estado da Sessão: não importa o coletor inteiro (~60 ms contra ~240 ms)
    function buildSessionCommand() {
        return "bash -c 'if command -v ai-usage-session-state >/dev/null 2>&1; then ai-usage-session-state; " +
               "elif [ -x \"$HOME/.local/bin/ai-usage-session-state\" ]; then \"$HOME/.local/bin/ai-usage-session-state\"; " +
               "elif [ -x \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-session-state\" ]; then \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-session-state\"; " +
               "elif command -v ai-usage-collector >/dev/null 2>&1; then ai-usage-collector --session-state; " +  // instalação antiga, sem o caminho leve
               "elif [ -x \"$HOME/.local/bin/ai-usage-collector\" ]; then \"$HOME/.local/bin/ai-usage-collector\" --session-state; " +
               "elif [ -x \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" ]; then \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" --session-state; " +
               "else python3 -m ai_usage_collector --session-state; fi'";
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
                var errMsg = stderr || stdout || I18n.tr("Exit code %1", exitCode);
                root.lastError = I18n.tr("Error running the collector: %1", errMsg);
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
            root.lastError = I18n.tr("The collector did not respond within 120 s; retrying on the next cycle.");
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

    // Execução da CLI de cada provedor: leitura barata de /proc pelo coletor, só com a opção ligada
    Plasma5Support.DataSource {
        id: runningDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            if (data["exit code"] === 0) root.loadStatus();
            disconnectSource(sourceName);
        }
    }

    Timer {
        interval: 15000
        repeat: true
        running: NotchModel.hideMode(root.statusData) !== "off"
        triggeredOnStart: true
        onTriggered: {
            root.nowMs = Date.now();  // antes da chamada: se o coletor falhar, a leitura velha ainda expira
            if (runningDataSource.connectedSources.length === 0)
                runningDataSource.connectSource(root.buildCollectorCommand(root.shellQuote("--detect-running")));
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
                    root.nowMs = Date.now();
                    root.statusData = parsed;
                    root.lastError = "";
                } catch (e) {
                    root.lastError = I18n.tr("Error reading status JSON: %1", e.message);
                }
            } else {
                if (exitCode !== 0) {
                    root.lastError = I18n.tr("Status cache not found. Run the collector.");
                }
            }
            disconnectSource(sourceName);
        }
    }

    // Estado da Sessão (ADR-0009): só consulta com a opção ligada; nada toca em hooks aqui
    property bool sessionPolling: false
    property bool autoOpened: false
    property bool sessionFailed: false  // consulta do estado falhou: aviso discreto na configuração e no tooltip

    property var sessionConfirmed: ({})  // "codex/<id>" -> ociosa confirmada pelo notify (fim real do turno)

    function applySessionStates(byProvider) {
        var prev = root.sessionOverlay || {};
        var prevConf = root.sessionConfirmed || {};
        var next = {};
        var confirmed = {};
        var list = (byProvider && byProvider.codex_idle_confirmed) || [];
        for (var i = 0; i < list.length; i++) confirmed["codex/" + list[i]] = true;
        for (var p in (byProvider || {})) {
            if (p === "codex_idle_confirmed") continue;
            for (var aid in byProvider[p]) next[p + "/" + aid] = byProvider[p][aid];
        }
        var fired = false;
        for (var id in next) {
            // só transições observadas: a 1ª leitura nunca dispara; terminou = ocupada -> ociosa.
            // Codex: ociosa por silêncio do log (turno longo sem escrita) oscila e não conta; só a ociosa
            // confirmada pelo notify, no momento em que passa a confirmada (ADR-0009)
            var was = prev[id];
            if (was === undefined || was === next[id] && !(id.indexOf("codex/") === 0 && confirmed[id] && !prevConf[id])) continue;
            if (next[id] === "waiting") fired = true;
            else if (next[id] === "idle") {
                if (id.indexOf("codex/") !== 0) fired = fired || was === "busy";
                else fired = fired || (confirmed[id] === true && !prevConf[id]);
            }
        }
        root.sessionOverlay = next;
        root.sessionConfirmed = confirmed;
        if (fired) root.sessionAttention();
    }

    // Abre o Notch por 5 s e toca o som, só se o usuário ligou cada opção. Não abre se o popup já está
    // aberto (nem fixado) e não altera pinned. Limitação: abrir o popup pode roubar o foco do teclado do
    // terminal onde o usuário digita; por isso a abertura automática é desligável (sessionAutoOpen).
    function sessionAttention() {
        if (Plasmoid.configuration.sessionAutoOpen === true && !root.expanded && !root.pinned && !root.idleHidden) {
            root.autoOpened = true;
            root.expanded = true;
            sessionCloseTimer.restart();
        }
        if (Plasmoid.configuration.sessionSound === true) {
            soundDataSource.connectSource("sh -c 'command -v canberra-gtk-play >/dev/null 2>&1 && canberra-gtk-play -i complete || paplay /usr/share/sounds/freedesktop/stereo/complete.oga' 2>/dev/null; true");
        }
    }

    // Fim dos 5 s: fixado ou com o mouse em cima, não fecha (o hover normal assume e fecha ao sair)
    Timer {
        id: sessionCloseTimer
        interval: 5000
        onTriggered: {
            var mine = root.autoOpened && root.expanded;
            root.autoOpened = false;
            if (!mine || root.pinned) return;
            if (root.pillHovered || root.popupHovered) { root.openedByHover = true; return; }
            root.expanded = false;
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
                root.sessionFailed = data["exit code"] !== 0;
                if (!root.sessionFailed) root.applySessionStates(JSON.parse(data["stdout"]));
            } catch (e) { root.sessionFailed = true; /* leitura inválida: mantém o último estado */ }
            disconnectSource(sourceName);
        }
    }

    Timer {
        interval: 5000
        repeat: true
        running: Plasmoid.configuration.sessionState === true && root.visible && !root.idleHidden
        triggeredOnStart: true
        onTriggered: {
            if (root.sessionPolling) return;
            root.sessionPolling = true;
            sessionDataSource.connectSource(root.buildSessionCommand());
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
        if (!root.expanded) {
            root.pinned = false;
            root.openedByHover = false;
            root.popupHovered = false;
            hoverOpenTimer.stop();
            hoverCloseTimer.stop();
        }
        if (root.expanded && (Plasmoid.configuration.autoRefreshOnExpand !== false)) {
            root.loadStatus();
        }
    }

    Component.onCompleted: {
        if (root.idleWanted) idleDelay.restart();
        if (root.rawIdle !== "") providerIdleDelay.restart();
        root.loadStatus();
    }

    compactRepresentation: CompactRepresentation {
        plasmoidItem: root
    }

    fullRepresentation: FullRepresentation {
        plasmoidItem: root
    }
}
