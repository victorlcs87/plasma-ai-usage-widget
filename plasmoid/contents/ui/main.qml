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
import "Collector.js" as Collector

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
    // Notch flutuante (ticket 41): com ele ativo o popup é o da janela flutuante (floatOpen) e o popup nativo do
    // Plasma nunca abre; sem ele, `open` é exatamente `expanded` (modo Plasmoid inalterado).
    property bool floatOpen: false
    readonly property bool floatingActive: floatingLoader.status === Loader.Ready && floatingLoader.item !== null && floatingLoader.item.available === true
    readonly property bool open: floatingActive ? floatOpen : expanded
    function setOpen(v) { if (floatingActive) floatOpen = v; else expanded = v; }
    // Opção desligada (ou layer-shell que falhou) com o popup flutuante aberto: nada fica para trás e religar
    // nunca abre o popup sozinho
    onFloatingActiveChanged: if (!floatingActive) {
        floatOpen = false; pinned = false; openedByHover = false; popupHovered = false;
        hoverOpenTimer.stop(); hoverCloseTimer.stop();
    }
    // Atalho global / ativação do Plasma com o flutuante ligado: alterna o popup flutuante, não o nativo
    onExpandedChanged: if (floatingActive && expanded) { expanded = false; setOpen(!floatOpen); }
    property bool pillHovered: false
    property bool popupHovered: false
    property double now: Date.now()
    // Só fecha por hover o popup que o hover abriu (ou que foi solto); atalho/ação externa nunca
    property bool openedByHover: false
    // Provedor destacado no topo do popup (ticket 48): só o clique num item o define; hover nunca. Vive só em
    // memória (não vai para a configuração) e é apagado ao fechar o popup.
    property string highlightProvider: ""
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
        && !root.open && !Plasmoid.userConfiguring && !root.pillHovered && !root.pinned && !root.popupHovered
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
    // Acento é forma (arco, borda de foco) sobre o Notch escuro: piso de 3:1 também com o realce escuro do Plasma
    readonly property color accentRaw: Presets.accentColor(Plasmoid.configuration.accentPreset, Kirigami.Theme.highlightColor)
    readonly property color accentColor: Presets.onPill(accentRaw.r, accentRaw.g, accentRaw.b, 3)

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
        var base = summaryToolTipBody();
        return collectorAttention ? I18n.tr("Collector needs attention") + "\n" + base : base;
    }

    function summaryToolTipBody() {
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
            if (hoverOpen && !open) hoverOpenTimer.restart();
        } else {
            hoverOpenTimer.stop();
            scheduleHoverClose();
        }
    }

    function scheduleHoverClose() {
        if (hoverOpen && open && openedByHover && !pinned && !pillHovered && !popupHovered) hoverCloseTimer.restart();
    }

    function setPopupHovered(h) {
        popupHovered = h;
        if (h) hoverCloseTimer.stop();
        else scheduleHoverClose();
    }

    // Clique: fecha/abre como antes; com hover ligado, clicar no popup aberto por hover o fixa, e de novo o solta
    // `provider`: item clicado no painel ("" = clique sem item, ex.: teclado). Fechar ou soltar não troca o destaque.
    function pillClicked(provider) {
        hoverOpenTimer.stop();
        if (!(open && (!hoverOpen || pinned))) highlightProvider = provider || "";
        if (!hoverOpen) { setOpen(!open); return; }
        if (!open) { pinned = true; setOpen(true); }
        else {
            pinned = !pinned;
            if (!pinned) { openedByHover = true; scheduleHoverClose(); }  // solto: volta a fechar ao sair
        }
    }

    function closePopup() {
        pinned = false;
        setOpen(false);
    }

    // Abre depois de ~300 ms com o mouse sobre a pílula
    Timer {
        id: hoverOpenTimer
        interval: 300
        onTriggered: if (root.hoverOpen && root.pillHovered && !root.open) { root.openedByHover = true; root.setOpen(true); }
    }

    // Atraso curto de saída: o mouse transita pílula -> popup sem piscar
    Timer {
        id: hoverCloseTimer
        interval: 250
        onTriggered: if (root.hoverOpen && root.openedByHover && !root.pinned && !root.pillHovered && !root.popupHovered) root.setOpen(false)
    }

    // Contagem regressiva da dica: só enquanto o mouse está na pílula com o popup fechado
    Timer {
        id: tooltipTick
        interval: 1000
        repeat: true
        running: root.pillHovered && !root.open
        onTriggered: root.now = Date.now()
    }

    // Instalador do Coletor (ADR-0012), só o estado: `status` roda na partida, ao abrir o popup e quando o cache
    // falta, no máximo uma vez a cada 30 s, e de hora em hora; nunca no laço de 15 s. A instalação (ticket 50) fica mais abaixo.
    property var collectorStatus: null
    readonly property bool collectorAttention: Collector.needsAttention(collectorStatus)
    readonly property string widgetVersion: Plasmoid.metaData ? String(Plasmoid.metaData.version || "") : ""
    property double collectorCheckedAt: 0
    readonly property string cacheMissingPlain: I18n.tr("Status cache not found. Run the collector.")
    readonly property string cacheMissingCard: I18n.tr("Status cache not found. See the collector notice.")

    function checkCollector() {
        var t = Date.now();
        if (root.widgetVersion === "" || t - root.collectorCheckedAt < 30000) return;
        // durante o install um status obsoleto não pode julgar o pós-install; o recheck (verifying) é permitido
        if (root.collectorInstall.state === "running" && !root.collectorInstall.verifying) return;
        root.collectorCheckedAt = t;
        var script = Collector.scriptPath(Qt.resolvedUrl("../code/collector-installer.py"));
        statusCheckSource.connectSource(Collector.buildStatusCommand(script, root.widgetVersion, Plasmoid.configuration.collectorPath));
    }

    Plasma5Support.DataSource {
        id: statusCheckSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            root.collectorStatus = Collector.parseStatus(data["stdout"] || "", data["exit code"]);
            if (root.collectorInstall.verifying)  // recheck pós-install: ok => idle; senão erro de verificação
                root.collectorInstall = root.collectorAttention ? { state: "error", cause: "verificacao", message: "", log: [], failedStep: "verify" } : { state: "idle" };
            // O aviso de cache ausente remete ao card quando o coletor precisa de atenção
            if (root.lastError === root.cacheMissingPlain || root.lastError === root.cacheMissingCard)
                root.lastError = root.collectorAttention ? root.cacheMissingCard : root.cacheMissingPlain;
            disconnectSource(sourceName);
        }
    }

    // Instalação do Coletor (ticket 50): SÓ pelo clique + confirmação no popup (installCollector); nunca na partida,
    // por timer ou ao abrir o popup. O DataSource vive aqui (não no popup): fechar o popup não interrompe o install.
    // state: idle | running | error. O engine "executable" entrega stdout/exit code ao fim; se vier parcial (sem
    // "exit code"), só o passo atual é atualizado.
    property var collectorInstall: ({ state: "idle" })

    function installCollector() {
        if (root.collectorInstall.state === "running" || root.widgetUpdateBusy) return;  // um único install/atualização por vez
        var script = Collector.scriptPath(Qt.resolvedUrl("../code/collector-installer.py"));
        var cmd = Collector.buildInstallCommand(script, root.widgetVersion);  // "" se a versão não for X.Y.Z
        if (cmd === "") {
            root.collectorInstall = { state: "error", cause: "falha", message: "", log: [], failedStep: "" };
            return;
        }
        root.collectorInstall = { state: "running", step: "" };
        installSource.connectSource(cmd);
    }

    Plasma5Support.DataSource {
        id: installSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            var out = data["stdout"] || "";
            if (data["exit code"] === undefined) {  // saída parcial: só o progresso
                root.collectorInstall = { state: "running", step: Collector.currentStep(out) };
                return;
            }
            disconnectSource(sourceName);
            var r = Collector.parseInstall(out, data["exit code"]);
            if (!r.ok) {
                root.collectorInstall = { state: "error", cause: r.cause, message: r.message, log: r.log, failedStep: r.failedStep };
                return;
            }
            root.collectorInstall = { state: "running", step: "verify", verifying: true };  // fica "running" até o recheck do status
            root.collectorCheckedAt = 0;  // o recheck do status não pode cair na janela de 30 s
            root.checkCollector();
            root.runCollectorRefresh(null, false);  // dados sem reiniciar o Plasma (somente --refresh)
        }
    }

    Timer {
        interval: 3600000
        repeat: true
        running: true
        onTriggered: root.checkCollector()
    }

    // Atualização do Widget (ticket 77, ADR-0014): Coletor + .plasmoid pela versão nova do GitHub Releases. SÓ pelo clique
    // (checkWidgetUpdate / askWidgetUpdate -> startWidgetUpdate); nunca na partida, por timer ou ao abrir o popup. Os
    // DataSources vivem aqui (fechar o popup não interrompe) e o estado é compartilhado por todo menu que instanciar
    // WidgetUpdate.qml. state: idle | buscando | confirmando | atualizando | concluido | erro.
    // result (última busca): "" | nova | atual | indisponivel | desligada. Em erro: cause, message, log, failedStep.
    property var widgetUpdate: ({ state: "idle", result: "", version: "", step: "" })
    // Debounce: após uma busca o botão fica desligado por alguns segundos (sem rajada ao GitHub)
    property bool widgetCheckCooldown: false
    // Versão nova conhecida (busca desta sessão ou o aviso do status.json), "" se não há ou se a busca disse "atual"
    readonly property string widgetUpdateVersion: widgetUpdate.result === "nova" ? widgetUpdate.version
        : widgetUpdate.result === "" && updateInfo.widget ? Collector.cleanVersion(updateInfo.widget.latest) : ""
    readonly property bool widgetUpdateBusy: widgetUpdate.state === "buscando" || widgetUpdate.state === "atualizando"

    function setWidgetUpdate(state, extra) { root.widgetUpdate = Collector.nextWidgetUpdate(root.widgetUpdate, state, extra); }

    function checkWidgetUpdate() {
        if (root.widgetUpdateBusy || root.widgetCheckCooldown || root.widgetUpdate.state === "confirmando" || root.widgetUpdate.state === "concluido") return;
        setWidgetUpdate("buscando", { result: "", version: "" });
        widgetCheckSource.connectSource(buildCollectorCommand(Collector.shellQuote("--check-update")));
    }
    property bool widgetAskFromConfig: false  // a confirmação veio da janela de configuração: fechar o popup não a cancela
    function askWidgetUpdate(fromConfig) {  // abre a confirmação inline; nada roda ainda
        if (root.widgetUpdateBusy || root.widgetUpdateVersion === "" || root.collectorInstall.state === "running") return;
        root.widgetAskFromConfig = fromConfig === true;
        setWidgetUpdate("confirmando", {});
    }
    function cancelWidgetUpdate(origin) {  // origin "popup": o popup fechou
        if (origin === "popup" && root.widgetAskFromConfig) return;
        if (root.widgetUpdate.state === "confirmando") setWidgetUpdate("idle", {});
    }
    function startWidgetUpdate() {
        if (root.widgetUpdate.state !== "confirmando" || root.collectorInstall.state === "running") return;  // clique repetido não duplica
        var script = Collector.scriptPath(Qt.resolvedUrl("../code/collector-installer.py"));
        var cmd = Collector.buildUpdateCommand(script, root.widgetUpdateVersion);  // "" se a versão não for X.Y.Z
        if (cmd === "") { setWidgetUpdate("erro", { cause: "falha", message: "", log: [], failedStep: "" }); return; }
        setWidgetUpdate("atualizando", { to: root.widgetUpdateVersion });
        widgetUpdateSource.connectSource(cmd);
    }
    // Recarrega o plasmashell; só depois do clique + confirmação do usuário no card (o QML antigo segue em memória até lá)
    function reloadWidget() {
        if (root.widgetUpdate.state === "concluido") widgetReloadSource.connectSource(Collector.reloadCommand());
    }

    Plasma5Support.DataSource {
        id: widgetCheckSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            if (data["exit code"] === undefined) return;  // parcial: espera o fim
            disconnectSource(sourceName);
            if (root.widgetUpdate.state !== "buscando") return;  // watchdog já encerrou a busca
            var r = Collector.parseCheckUpdate(data["stdout"] || "");
            root.setWidgetUpdate("idle", { result: r.update, version: r.version });
            root.widgetCheckCooldown = true;
            widgetCooldown.restart();
        }
    }
    Timer { id: widgetCooldown; interval: 5000; onTriggered: root.widgetCheckCooldown = false }

    Plasma5Support.DataSource {
        id: widgetUpdateSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            var r = Collector.widgetUpdateOnData(root.widgetUpdate, data["stdout"] || "", data["exit code"]);
            if (r.done) disconnectSource(sourceName);
            root.widgetUpdate = r.next;
        }
    }
    // Watchdog: busca presa (~30 s) ou atualização presa (~10 min) vira erro "falha" e solta os DataSources
    Timer {
        interval: root.widgetUpdate.state === "buscando" ? 30000 : 600000
        running: root.widgetUpdateBusy
        onTriggered: {
            var next = Collector.widgetUpdateStuck(root.widgetUpdate);
            if (next === null) return;
            widgetCheckSource.connectedSources = [];
            widgetUpdateSource.connectedSources = [];
            root.widgetUpdate = next;
        }
    }
    // Menus (painel e Notch): um único rótulo/estado para os dois e uma única entrada, `requestWidgetUpdate`. Ela nunca atualiza:
    // só busca ou abre a confirmação inline e mostra o popup, onde o WidgetUpdate pede versão/origem/sem sudo.
    readonly property string widgetUpdateActionText: widgetUpdate.state === "buscando" ? I18n.tr("Checking for updates…")
        : widgetUpdate.state === "atualizando" ? I18n.tr("Updating the widget…")
        : widgetUpdate.state === "concluido" ? I18n.tr("Reload the widget")
        : widgetUpdate.state === "erro" && widgetUpdateVersion !== "" ? I18n.tr("Retry update to v%1", widgetUpdateVersion)
        : widgetUpdateVersion !== "" ? I18n.tr("Update to v%1", widgetUpdateVersion) : I18n.tr("Check for updates")
    readonly property bool widgetUpdateActionEnabled: !widgetUpdateBusy && collectorInstall.state !== "running" && (widgetUpdateVersion !== "" || widgetUpdate.state === "concluido" || !widgetCheckCooldown)
    function requestWidgetUpdate() {
        if (!root.widgetUpdateActionEnabled) return;
        if (root.widgetUpdate.state === "idle" || root.widgetUpdate.state === "erro") {
            if (root.widgetUpdateVersion !== "") root.askWidgetUpdate(); else root.checkWidgetUpdate();
        }
        root.setOpen(true);
        if (root.hoverOpen) { root.pinned = true; root.openedByHover = false; }  // como o pillClicked: o hover não fecha a confirmação
    }
    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            objectName: "widgetUpdateAction"
            text: root.widgetUpdateActionText
            icon.name: "update-none"
            enabled: root.widgetUpdateActionEnabled
            onTriggered: root.requestWidgetUpdate()
        }
    ]

    // Janela de configuração (outro contexto QML, sem acesso a este item): lê um espelho do estado e pede ações pela
    // própria configuração. Quem executa continua sendo só este arquivo, então não há execução dupla.
    readonly property string widgetUpdateMirror: JSON.stringify({ upd: { state: widgetUpdate.state, result: widgetUpdate.result, version: widgetUpdate.version,
        step: widgetUpdate.step, to: widgetUpdate.to, cause: widgetUpdate.cause, message: widgetUpdate.message, failedStep: widgetUpdate.failedStep },
        version: widgetUpdateVersion, current: widgetVersion, cooldown: widgetCheckCooldown })
    onWidgetUpdateMirrorChanged: Plasmoid.configuration.widgetUpdateMirror = root.widgetUpdateMirror
    Connections {
        target: Plasmoid.configuration
        function onWidgetUpdateRequestChanged() {
            var a = String(Plasmoid.configuration.widgetUpdateRequest || "").split(":")[0];
            if (a === "") return;
            Plasmoid.configuration.widgetUpdateRequest = "";
            if (a === "check") root.checkWidgetUpdate();
            else if (a === "ask") root.askWidgetUpdate(true);
            else if (a === "cancel") root.cancelWidgetUpdate();
            else if (a === "start") root.startWidgetUpdate();
            else if (a === "reload") root.reloadWidget();
        }
    }

    Plasma5Support.DataSource {  // desconecta ao receber dados: um segundo clique reexecuta o comando
        id: widgetReloadSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => disconnectSource(sourceName)
    }

    function buildCollectorCommand(quotedArgs) { return Collector.buildCollectorCommand(quotedArgs, Plasmoid.configuration.collectorPath); }
    function buildSessionCommand() { return Collector.buildSessionCommand(Plasmoid.configuration.collectorPath); }

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
        return Math.max(3600, Plasmoid.configuration[key] || 3600);
    }

    function runCollectorRefresh(dueProviders, forceRenew) {
        if (root.isRefreshing) return;
        var now = Date.now();
        var targets = dueProviders || root.providers;
        for (var i = 0; i < targets.length; i++) root.lastProviderRefresh[targets[i]] = now;

        var args = Collector.shellQuote("--refresh");
        if (forceRenew) args += " " + Collector.shellQuote("--force-renew");
        if (dueProviders) args += " " + Collector.shellQuote("--provider") + " " + Collector.shellQuote(dueProviders.join(","));
        for (var j = 0; j < root.providers.length; j++) {
            var p = root.providers[j];
            args += " " + Collector.shellQuote("--refresh-interval") + " " + Collector.shellQuote(p + "=" + providerInterval(p));
        }
        root.isRefreshing = true;
        root.lastError = "";
        collectorDataSource.connectSource(buildCollectorCommand(args));
    }

    // "Atualizar agora": ignora o intervalo de todos os provedores e força a renovação das Contas vencidas
    // (o agendador de 15 s nunca envia --force-renew)
    function refreshCollector() {
        runCollectorRefresh(null, true);
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
                runningDataSource.connectSource(root.buildCollectorCommand(Collector.shellQuote("--detect-running")));
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
        var safeArgs = Collector.shellQuote("--remove-account") + " " + Collector.shellQuote(provClean) + " " + Collector.shellQuote(accountId);
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
                    root.lastError = root.collectorAttention ? root.cacheMissingCard : root.cacheMissingPlain;
                    if (root.collectorStatus === null) root.checkCollector();  // estado ainda desconhecido; nunca em laço
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
        if (Plasmoid.configuration.sessionAutoOpen === true && !root.open && !root.pinned && !root.idleHidden) {
            root.autoOpened = true;
            root.setOpen(true);
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
            var mine = root.autoOpened && root.open;
            root.autoOpened = false;
            if (!mine || root.pinned) return;
            if (root.pillHovered || root.popupHovered) { root.openedByHover = true; return; }
            root.setOpen(false);
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
        var cmd = "cat " + Collector.shellQuote(statusFilePath) + " 2>/dev/null";
        statusDataSource.connectSource(cmd);
    }

    onOpenChanged: {
        if (!root.open) root.autoOpened = false;
        if (!root.open) {
            root.highlightProvider = "";
            root.pinned = false;
            root.openedByHover = false;
            root.popupHovered = false;
            hoverOpenTimer.stop();
            hoverCloseTimer.stop();
        }
        if (root.open) root.checkCollector();
        if (root.open && (Plasmoid.configuration.autoRefreshOnExpand !== false)) {
            root.loadStatus();
        }
    }

    Component.onCompleted: {
        Plasmoid.configuration.widgetUpdateMirror = root.widgetUpdateMirror;
        if (root.idleWanted) idleDelay.restart();
        if (root.rawIdle !== "") providerIdleDelay.restart();
        root.checkCollector();
        root.loadStatus();
    }

    // Janela flutuante: só é carregada (e FloatingNotch.qml só é resolvido) com a opção ligada
    Loader {
        id: floatingLoader
        // só no painel (no desktop o widget já é uma janela própria) e uma instância por tela (FloatingNotch.ownsScreen)
        active: Plasmoid.configuration.floatingNotch === true && root.inPanel
        source: "FloatingNotch.qml"
        onLoaded: item.plasmoidItem = root
    }

    compactRepresentation: CompactRepresentation {
        plasmoidItem: root
    }

    fullRepresentation: FullRepresentation {
        plasmoidItem: root
    }
}
