import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtCore

import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.plasma.extras as PlasmaExtras
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle
import "ViewPrefs.js" as ViewPrefs
import "FloatingGeometry.js" as FloatingGeometry
import "I18n.js" as I18n
import "Collector.js" as Collector

Item {
    id: configRoot

    implicitWidth: Kirigami.Units.gridUnit * 32
    implicitHeight: Kirigami.Units.gridUnit * 28

    // Texto de ajuda/secundário: texto do tema a 70% (>= 5:1 no Breeze claro e escuro; disabledTextColor dava 3,7:1)
    readonly property color secondaryText: Qt.alpha(Kirigami.Theme.textColor, 0.7)

    // Intervalo de Atualização por provedor (KConfigXT, main.xml)
    property int cfg_refreshIntervalClaude: 300
    property int cfg_refreshIntervalCodex: 300
    property int cfg_refreshIntervalGemini: 300
    property string cfg_collectorPath: ""

    // Notch compacto (KConfigXT): ordem, provedores ocultos e cor de destaque
    property string cfg_providerOrder: "claude,codex,gemini"
    property string cfg_hiddenProviders: ""
    property string cfg_accentPreset: "plasma"
    // Estado da Sessão (KConfigXT): os hooks só existem após `ai-usage-collector --install-hooks`
    property bool cfg_sessionState: false
    property bool cfg_sessionAutoOpen: false
    property bool cfg_sessionSound: false
    property bool cfg_hoverOpen: true
    // Estilo do painel (ticket 32): valores inválidos do arquivo caem no padrão (PanelStyle.config)
    property string cfg_panelStyle: "pill"
    property string cfg_panelMode: "ring"
    property string cfg_ringCenter: "logo"
    property int cfg_metricSize: 100
    property int cfg_panelMargin: -1  // -1 = automática (Kirigami.Units.smallSpacing)
    readonly property var panelNow: PanelStyle.config({ panelStyle: cfg_panelStyle, panelMode: cfg_panelMode, ringCenter: cfg_ringCenter,
                                                        metricSize: cfg_metricSize, panelMargin: cfg_panelMargin })
    // Notch flutuante (ticket 41): opcional, desligado por padrão; uma posição por borda (px a partir do centro)
    property bool cfg_floatingNotch: false
    property string cfg_floatEdge: "top"
    property int cfg_floatSize: 100
    property bool cfg_floatSnap: true
    property string cfg_floatScreen: ""
    property int cfg_floatOffsetTop: 0
    property int cfg_floatOffsetBottom: 0
    property int cfg_floatOffsetLeft: 0
    property int cfg_floatOffsetRight: 0
    readonly property var floatNow: FloatingGeometry.config({ floatingNotch: cfg_floatingNotch, floatEdge: cfg_floatEdge, floatSize: cfg_floatSize,
        floatSnap: cfg_floatSnap, floatScreen: cfg_floatScreen, floatOffsetTop: cfg_floatOffsetTop, floatOffsetBottom: cfg_floatOffsetBottom,
        floatOffsetLeft: cfg_floatOffsetLeft, floatOffsetRight: cfg_floatOffsetRight })
    function setFloatOffset(edge, v) {
        if (edge === "top") cfg_floatOffsetTop = v;
        else if (edge === "bottom") cfg_floatOffsetBottom = v;
        else if (edge === "left") cfg_floatOffsetLeft = v;
        else cfg_floatOffsetRight = v;
    }
    readonly property var providerOrderList: Presets.normalizeOrder(cfg_providerOrder)
    // Popup (ticket 33): exibição em todo o widget, opacidade do fundo, ordem e visibilidade dos cards
    property string cfg_usageDisplay: "used"
    property string cfg_resetDisplay: "countdown"
    property int cfg_popupOpacity: 100
    property string cfg_popupProviderOrder: "claude,codex,gemini"
    property string cfg_popupHiddenProviders: ""
    readonly property var viewNow: ViewPrefs.config({ usageDisplay: cfg_usageDisplay, resetDisplay: cfg_resetDisplay, popupOpacity: cfg_popupOpacity,
                                                      popupProviderOrder: cfg_popupProviderOrder, popupHiddenProviders: cfg_popupHiddenProviders })
    readonly property var popupOrderList: Presets.normalizeOrder(cfg_popupProviderOrder)

    function movePopupProvider(index, delta) {
        var list = popupOrderList.slice();
        var to = index + delta;
        if (to < 0 || to >= list.length) return;
        var tmp = list[index]; list[index] = list[to]; list[to] = tmp;
        cfg_popupProviderOrder = list.join(",");
    }

    function setPopupProviderHidden(key, hidden) {
        var list = cfg_popupHiddenProviders.split(",").filter(function (k) { return k && k !== key; });
        if (hidden) list.push(key);
        cfg_popupHiddenProviders = list.join(",");
    }

    function moveProvider(index, delta) {
        var list = providerOrderList.slice();
        var to = index + delta;
        if (to < 0 || to >= list.length) return;
        var tmp = list[index]; list[index] = list[to]; list[to] = tmp;
        cfg_providerOrder = list.join(",");
    }

    function setProviderHidden(key, hidden) {
        var list = cfg_hiddenProviders.split(",").filter(function (k) { return k && k !== key; });
        if (hidden) list.push(key);
        cfg_hiddenProviders = list.join(",");
    }

    // Alertas (config.json do coletor, lidos do status.json): modo "pace" ou "threshold" e limiares
    property string alertMode: "pace"
    property int alertWarning: 70
    property int alertCritical: 90
    property bool isSavingAlerts: false
    property bool alertsDirty: false  // edição em curso (não aplicada): o status recarregado não a sobrescreve

    // Notificações de limite (config.json do coletor, lidas do status.json)
    property int notifyWarning: 80
    property int notifyCritical: 95
    property bool notifyEarly: true
    property bool notifyReset: false
    property var notifyMuted: []
    property bool notifyThresholdsEdited: false  // limiares só são enviados se editados: valores fracionários existentes não são arredondados
    property bool isSavingNotify: false
    property bool notifyDirty: false  // edição em curso (não aplicada): o status recarregado não a sobrescreve

    // Verificação diária de atualização (config.json do coletor, lida do status.json)
    property bool updateCheck: true
    property bool isSavingUpdates: false
    property bool updateCheckBefore: true  // valor anterior, restaurado se o coletor falhar
    // Ocultar sem o processo da CLI (config.json do coletor, lido do status.json): off (padrão) | widget | provider
    property string hideMode: "off"
    property bool isSavingHide: false
    property bool hideDirty: false

    property var statusData: null
    property bool isLoading: false
    property bool isDeleting: false
    property bool isRenaming: false
    property bool isAdding: false
    property bool isCapturing: false
    property bool isInteractiveLogin: false
    property bool isAddFormExpanded: false
    property bool isAdvancedExpanded: false
    property string statusMessage: ""
    property string errorMessage: ""
    property var accountPendingDeletion: null
    property var accountPendingRename: null
    property var orphanPendingDeletion: null
    readonly property var orphanProfiles: (statusData && statusData.orphan_profiles) ? statusData.orphan_profiles : []

    readonly property bool isBusy: isLoading || isDeleting || isRenaming || isAdding || isCapturing || isInteractiveLogin

    function buildCollectorCommand(quotedArgs) { return Collector.buildCollectorCommand(quotedArgs, configRoot.cfg_collectorPath); }

    function healthTone(status) { return status === "valid" ? "#27ae60" : status === "session_expired" ? "#f39c12" : "#7f8c8d"; }

    function getProviderColor(provider) {
        switch ((provider || "").toLowerCase()) {
        case "claude":
            return "#d97736"; // Coral Anthropic
        case "codex":
            return "#10a37f"; // Verde OpenAI
        case "gemini":
            return "#4285f4"; // Azul Google
        default:
            return Kirigami.Theme.highlightColor;
        }
    }

    function getAccountsList() {
        if (!statusData || !statusData.agents) {
            return [];
        }
        var list = [];
        var agents = statusData.agents;
        var providers = ["claude", "codex", "gemini"];
        for (var p = 0; p < providers.length; p++) {
            var provKey = providers[p];
            if (agents[provKey] && agents[provKey].accounts && Array.isArray(agents[provKey].accounts)) {
                var accs = agents[provKey].accounts;
                for (var i = 0; i < accs.length; i++) {
                    var acc = accs[i];
                    list.push({
                        provider: provKey,
                        id: acc.id || "default",
                        name: acc.name || acc.label || acc.id || provKey,
                        source: acc.source || "auto",
                        healthStatus: acc.health?.status || "unknown",
                        healthMessage: acc.health?.message || "",
                        usedCapacity: acc.native_window?.used_capacity,
                        totalCapacity: acc.native_window?.total_capacity,
                        usagePercentage: acc.native_window?.usage_percentage
                    });
                }
            }
        }
        return list;
    }

    function getDefaultPath(provider) {
        var prov = (provider || "").toLowerCase().trim();
        if (prov === "claude") {
            return "~/.claude";
        } else if (prov === "codex") {
            return "~/.codex";
        } else if (prov === "gemini") {
            return "~/.gemini";
        }
        return "";
    }

    function clearAddAccountForm() {
        accountNameField.text = "";
        credentialPathField.text = "";
        inviteUrlField.text = "";
    }

    function addAccount() {
        var prov = (providerComboBox.currentText || "Claude").toLowerCase().trim();
        var label = (accountNameField.text || "").trim();
        var path = (credentialPathField.text || "").trim();
        var inviteUrl = (inviteUrlField.text || "").trim();

        if (!label) {
            configRoot.errorMessage = I18n.tr("Please fill in the account nickname/name.");
            return;
        }
        if (!path) {
            configRoot.errorMessage = I18n.tr("Please enter the credentials path or directory.");
            return;
        }

        configRoot.isAdding = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var safeArgs = Collector.shellQuote("--add-account") + " " +
                       Collector.shellQuote("--provider") + " " + Collector.shellQuote(prov) + " " +
                       Collector.shellQuote("--label") + " " + Collector.shellQuote(label) + " " +
                       Collector.shellQuote("--credential-path") + " " + Collector.shellQuote(path);

        if (inviteUrl.length > 0) {
            safeArgs += " " + Collector.shellQuote("--invite-url") + " " + Collector.shellQuote(inviteUrl);
        }
        safeArgs += " " + Collector.shellQuote("--status");

        var cmd = configRoot.buildCollectorCommand(safeArgs);
        additionDataSource.connectSource(cmd);
    }

    function captureCurrentAccount() {
        var prov = (providerComboBox.currentText || "Claude").toLowerCase().trim();
        var label = (accountNameField.text || "").trim();

        configRoot.isCapturing = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var safeArgs = Collector.shellQuote("--capture-current") + " " + Collector.shellQuote(prov);
        if (label.length > 0) {
            safeArgs += " " + Collector.shellQuote("--name") + " " + Collector.shellQuote(label);
        }
        safeArgs += " " + Collector.shellQuote("--status");

        var cmd = configRoot.buildCollectorCommand(safeArgs);
        captureDataSource.connectSource(cmd);
    }

    function interactiveLoginAccount() {
        var prov = (providerComboBox.currentText || "Claude").toLowerCase().trim();
        var label = (accountNameField.text || "").trim();

        configRoot.isInteractiveLogin = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var safeArgs = Collector.shellQuote("--interactive-login") + " " + Collector.shellQuote(prov);
        if (label.length > 0) {
            safeArgs += " " + Collector.shellQuote("--name") + " " + Collector.shellQuote(label);
        }
        safeArgs += " " + Collector.shellQuote("--status");

        var cmd = configRoot.buildCollectorCommand(safeArgs);
        interactiveLoginDataSource.connectSource(cmd);
    }

    // Leitor de status para a tela de configurações
    Plasma5Support.DataSource {
        id: configStatusDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isLoading = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();

            if (exitCode === 0 && stdout.length > 0) {
                try {
                    configRoot.statusData = JSON.parse(stdout);
                    var al = configRoot.statusData.alerts;
                    if (al && !configRoot.isSavingAlerts && !configRoot.alertsDirty) {
                        configRoot.alertMode = al.mode === "threshold" ? "threshold" : "pace";
                        configRoot.alertWarning = Math.round(Number(al.warning)) || 70;
                        configRoot.alertCritical = Math.round(Number(al.critical)) || 90;
                    }
                    var up = configRoot.statusData.updates;
                    if (up && typeof up.enabled === "boolean" && !configRoot.isSavingUpdates) configRoot.updateCheck = up.enabled;
                    var vis = configRoot.statusData.visibility;
                    if (vis && !configRoot.isSavingHide && !configRoot.hideDirty) {
                        configRoot.hideMode = (vis.hide_when_not_running === "widget" || vis.hide_when_not_running === "provider") ? vis.hide_when_not_running : "off";
                    }
                    var nt = configRoot.statusData.notifications;
                    if (nt && !configRoot.isSavingNotify && !configRoot.notifyDirty) {
                        configRoot.notifyWarning = Math.round(Number(nt.warning)) || 80;
                        configRoot.notifyCritical = Math.round(Number(nt.critical)) || 95;
                        configRoot.notifyEarly = nt.early !== false;
                        configRoot.notifyReset = nt.reset === true;
                        configRoot.notifyMuted = Array.isArray(nt.muted) ? nt.muted : [];
                    }
                } catch (e) {
                    configRoot.errorMessage = I18n.tr("Error reading status data: %1", e.message);
                }
            }
            disconnectSource(sourceName);
        }
    }

    // Modo e limiares de alerta: o coletor valida (0 < aviso < crítico <= 100) e recalcula o status
    function saveAlertSettings() {
        configRoot.isSavingAlerts = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";
        var args = Collector.shellQuote("--set-alert-config") + " " + Collector.shellQuote("--alert-mode") + " " + Collector.shellQuote(configRoot.alertMode)
            + " " + Collector.shellQuote("--alert-warning") + " " + Collector.shellQuote(configRoot.alertWarning)
            + " " + Collector.shellQuote("--alert-critical") + " " + Collector.shellQuote(configRoot.alertCritical);
        alertDataSource.connectSource(configRoot.buildCollectorCommand(args));
    }

    Plasma5Support.DataSource {
        id: alertDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isSavingAlerts = false;
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();
            if (data["exit code"] === 0) {
                configRoot.alertsDirty = false;
                configRoot.statusMessage = stdout.split("\n")[0];
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = stderr || stdout || I18n.tr("Unknown error");
            }
            disconnectSource(sourceName);
        }
    }

    // Ocultar sem o processo da CLI: o coletor valida o modo e o expõe no status
    function saveHideSettings() {
        configRoot.isSavingHide = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";
        hideDataSource.connectSource(configRoot.buildCollectorCommand(
            Collector.shellQuote("--set-visibility-config") + " " + Collector.shellQuote("--hide-when-not-running") + " " + Collector.shellQuote(configRoot.hideMode)));
    }

    Plasma5Support.DataSource {
        id: hideDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isSavingHide = false;
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();
            if (data["exit code"] === 0) {
                configRoot.hideDirty = false;
                configRoot.statusMessage = stdout.split("\n")[0];
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = stderr || stdout || I18n.tr("Unknown error");
            }
            disconnectSource(sourceName);
        }
    }

    // Notificações: o coletor valida (0 < aviso < crítico <= 100) e as envia pelo D-Bus
    function saveNotifySettings() {
        configRoot.isSavingNotify = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";
        var args = Collector.shellQuote("--set-notify-config");
        if (configRoot.notifyThresholdsEdited) {
            args += " " + Collector.shellQuote("--notify-warning") + " " + Collector.shellQuote(configRoot.notifyWarning)
                + " " + Collector.shellQuote("--notify-critical") + " " + Collector.shellQuote(configRoot.notifyCritical);
        }
        args += " " + Collector.shellQuote("--notify-early") + " " + Collector.shellQuote(configRoot.notifyEarly ? "on" : "off")
            + " " + Collector.shellQuote("--notify-reset") + " " + Collector.shellQuote(configRoot.notifyReset ? "on" : "off")
            + " " + Collector.shellQuote("--notify-mute") + " " + Collector.shellQuote(configRoot.notifyMuted.join(","));
        notifyDataSource.connectSource(configRoot.buildCollectorCommand(args));
    }

    function saveUpdateSetting(enabled) {
        configRoot.updateCheckBefore = !enabled;
        configRoot.isSavingUpdates = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";
        updateDataSource.connectSource(configRoot.buildCollectorCommand(
            Collector.shellQuote("--set-update-config") + " " + Collector.shellQuote("--update-check") + " " + Collector.shellQuote(enabled ? "on" : "off")));
    }

    Plasma5Support.DataSource {
        id: updateDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isSavingUpdates = false;
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();
            if (data["exit code"] === 0) {
                configRoot.statusMessage = stdout.split("\n")[0];
                configRoot.loadStatus();
            } else {
                configRoot.updateCheck = configRoot.updateCheckBefore;
                updateCheckBox.checked = configRoot.updateCheckBefore;
                configRoot.errorMessage = stderr || stdout || I18n.tr("Unknown error");
            }
            disconnectSource(sourceName);
        }
    }

    function setProviderMuted(provider, muted) {
        var list = configRoot.notifyMuted.filter(function (p) { return p !== provider; });
        if (muted) list.push(provider);
        configRoot.notifyMuted = list;
        configRoot.notifyDirty = true;
    }

    Plasma5Support.DataSource {
        id: notifyDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isSavingNotify = false;
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();
            if (data["exit code"] === 0) {
                configRoot.notifyDirty = false;
                configRoot.notifyThresholdsEdited = false;
                configRoot.statusMessage = stdout.split("\n")[0];
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = stderr || stdout || I18n.tr("Unknown error");
            }
            disconnectSource(sourceName);
        }
    }

    // Executor de remoção de conta
    Plasma5Support.DataSource {
        id: removalDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isDeleting = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                configRoot.statusMessage = I18n.tr("Account removed successfully!");
                configRoot.errorMessage = "";
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = I18n.tr("Failed to remove account: %1", stderr || stdout || I18n.tr("Unknown error"));
                configRoot.statusMessage = "";
            }
            disconnectSource(sourceName);
        }
    }

    // Perfis Órfãos: reimportar ou excluir (a exclusão só roda com --confirm, após o diálogo)
    function runOrphanAction(flag, orphan, confirm) {
        configRoot.isLoading = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";
        var args = Collector.shellQuote(flag) + " " + Collector.shellQuote(orphan.provider) + " " + Collector.shellQuote(orphan.id) + (confirm ? " " + Collector.shellQuote("--confirm") : "");
        orphanDataSource.connectSource(configRoot.buildCollectorCommand(args));
    }

    Plasma5Support.DataSource {
        id: orphanDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isLoading = false;
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();
            if (data["exit code"] === 0) {
                configRoot.statusMessage = stdout.split("\n")[0];
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = stderr || stdout || I18n.tr("Unknown error");
            }
            disconnectSource(sourceName);
        }
    }

    // Executor de renomeação de conta
    Plasma5Support.DataSource {
        id: renameDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isRenaming = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                var lines = stdout.split("\n");
                var msg = lines[0] || I18n.tr("Account renamed successfully!");
                configRoot.statusMessage = msg;
                configRoot.errorMessage = "";
                var jsonStart = stdout.indexOf("{");
                if (jsonStart !== -1) {
                    try {
                        configRoot.statusData = JSON.parse(stdout.substring(jsonStart));
                    } catch (e) {
                        configRoot.loadStatus();
                    }
                } else {
                    configRoot.loadStatus();
                }
            } else {
                configRoot.errorMessage = I18n.tr("Failed to rename account: %1", stderr || stdout || I18n.tr("Unknown error"));
                configRoot.statusMessage = "";
            }
            disconnectSource(sourceName);
        }
    }

    // Executor de adição de conta
    Plasma5Support.DataSource {
        id: additionDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isAdding = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                configRoot.statusMessage = I18n.tr("Account added successfully!");
                configRoot.errorMessage = "";
                configRoot.clearAddAccountForm();
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = I18n.tr("Failed to add account: %1", stderr || stdout || I18n.tr("Unknown error"));
                configRoot.statusMessage = "";
            }
            disconnectSource(sourceName);
        }
    }

    // Executor de captura de sessão ativa do CLI
    Plasma5Support.DataSource {
        id: captureDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isCapturing = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                var lines = stdout.split("\n");
                var msg = lines[0] || I18n.tr("Active session captured successfully!");
                configRoot.statusMessage = msg;
                configRoot.errorMessage = "";
                configRoot.clearAddAccountForm();
                var jsonStart = stdout.indexOf("{");
                if (jsonStart !== -1) {
                    try {
                        configRoot.statusData = JSON.parse(stdout.substring(jsonStart));
                    } catch (e) {
                        configRoot.loadStatus();
                    }
                } else {
                    configRoot.loadStatus();
                }
            } else {
                configRoot.errorMessage = I18n.tr("Failed to capture current login: %1", stderr || stdout || I18n.tr("Unknown error"));
                configRoot.statusMessage = "";
            }
            disconnectSource(sourceName);
        }
    }

    // Executor de login interativo no terminal
    Plasma5Support.DataSource {
        id: interactiveLoginDataSource
        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            configRoot.isInteractiveLogin = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                var lines = stdout.split("\n");
                var msg = lines[0] || I18n.tr("Interactive login completed successfully!");
                configRoot.statusMessage = msg;
                configRoot.errorMessage = "";
                configRoot.clearAddAccountForm();
                var jsonStart = stdout.indexOf("{");
                if (jsonStart !== -1) {
                    try {
                        configRoot.statusData = JSON.parse(stdout.substring(jsonStart));
                    } catch (e) {
                        configRoot.loadStatus();
                    }
                } else {
                    configRoot.loadStatus();
                }
            } else {
                configRoot.errorMessage = I18n.tr("Interactive login failed: %1", stderr || stdout || I18n.tr("Unknown error"));
                configRoot.statusMessage = "";
            }
            disconnectSource(sourceName);
        }
    }

    function loadStatus() {
        configRoot.isLoading = true;
        var cacheLoc = StandardPaths.writableLocation(StandardPaths.GenericCacheLocation);
        var cachePath = (typeof cacheLoc === "string" ? cacheLoc : cacheLoc.toString()).replace(/^file:\/\//, "");
        var statusFilePath = cachePath + "/plasma-ai-usage/status.json";
        var cmd = "cat " + Collector.shellQuote(statusFilePath) + " 2>/dev/null";
        configStatusDataSource.connectSource(cmd);
    }

    function requestDeleteAccount(account) {
        configRoot.accountPendingDeletion = account;
        confirmDialog.open();
    }

    function confirmDelete() {
        if (!configRoot.accountPendingDeletion) return;
        var acc = configRoot.accountPendingDeletion;
        configRoot.isDeleting = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var provClean = String(acc.provider).toLowerCase().trim();
        var safeArgs = Collector.shellQuote("--remove-account") + " " + Collector.shellQuote(provClean) + " " + Collector.shellQuote(acc.id);
        var cmd = configRoot.buildCollectorCommand(safeArgs);
        removalDataSource.connectSource(cmd);
    }

    function requestRenameAccount(account) {
        configRoot.accountPendingRename = account;
        renameAccountField.text = account.name || account.id || "";
        renameDialog.open();
        renameAccountField.forceActiveFocus();
    }

    function confirmRename() {
        if (!configRoot.accountPendingRename) return;
        var newName = (renameAccountField.text || "").trim();
        if (!newName) {
            configRoot.errorMessage = I18n.tr("The account name cannot be empty.");
            return;
        }
        var acc = configRoot.accountPendingRename;
        configRoot.isRenaming = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var provClean = String(acc.provider).toLowerCase().trim();
        var safeArgs = Collector.shellQuote("--rename-account") + " " +
                       Collector.shellQuote(provClean) + " " +
                       Collector.shellQuote(acc.id) + " " +
                       Collector.shellQuote("--label") + " " +
                       Collector.shellQuote(newName) + " " +
                       Collector.shellQuote("--status");
        var cmd = configRoot.buildCollectorCommand(safeArgs);
        renameDataSource.connectSource(cmd);
    }

    Component.onCompleted: {
        configRoot.loadStatus();
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing * 2
        spacing: Kirigami.Units.smallSpacing

        // Cabeçalho de gerenciamento
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                textFormat: Text.PlainText
                level: 2
                text: I18n.tr("Configuration")
                Layout.fillWidth: true
            }

            PlasmaComponents3.Button {
                icon.name: "view-refresh"
                text: I18n.tr("Reload")
                display: QQC2.AbstractButton.IconOnly
                enabled: !configRoot.isBusy
                QQC2.ToolTip.text: I18n.tr("Refresh account list")
                QQC2.ToolTip.visible: hovered
                onClicked: {
                    configRoot.statusMessage = "";
                    configRoot.errorMessage = "";
                    configRoot.loadStatus();
                }
            }
        }

        // Barra de progresso durante carregamento, adição ou exclusão
        QQC2.ProgressBar {
            id: configProgressBar
            Layout.fillWidth: true
            Layout.preferredHeight: 4
            indeterminate: true
            visible: configRoot.isBusy
        }

        // Mensagem de sucesso
        Kirigami.InlineMessage {
            id: successInlineMessage
            Layout.fillWidth: true
            type: Kirigami.MessageType.Positive
            visible: configRoot.statusMessage.length > 0
            text: configRoot.statusMessage
            showCloseButton: true
            onVisibleChanged: {
                if (visible) {
                    messageAutoDismissTimer.restart();
                }
            }
        }

        // Mensagem de erro
        Kirigami.InlineMessage {
            id: errorInlineMessage
            Layout.fillWidth: true
            type: Kirigami.MessageType.Error
            visible: configRoot.errorMessage.length > 0
            text: configRoot.errorMessage
            showCloseButton: true
        }

        Timer {
            id: messageAutoDismissTimer
            interval: 5000
            running: false
            repeat: false
            onTriggered: {
                configRoot.statusMessage = "";
            }
        }

        // Abas (Geral abre por padrão)
        QQC2.TabBar {
            id: configTabBar
            objectName: "configTabBar"
            Layout.fillWidth: true
            currentIndex: 0
            Accessible.role: Accessible.PageTabList
            Accessible.name: I18n.tr("Settings sections")

            QQC2.TabButton {
                text: I18n.tr("General")
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: I18n.tr("General")
                Accessible.description: I18n.tr("General settings: refresh, alerts, hiding without a CLI and version checks")
            }
            QQC2.TabButton {
                text: I18n.tr("Panel")
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: I18n.tr("Panel")
                Accessible.description: I18n.tr("Appearance of the compact Notch in the panel")
            }
            QQC2.TabButton {
                text: I18n.tr("Popup")
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: I18n.tr("Popup")
                Accessible.description: I18n.tr("Popup: opening, display, opacity and providers")
            }
            QQC2.TabButton {
                text: I18n.tr("Accounts")
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: I18n.tr("Accounts")
                Accessible.description: I18n.tr("Registered accounts, creation, capture and orphan profiles")
            }
            QQC2.TabButton {
                text: I18n.tr("Notifications")
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: I18n.tr("Notifications")
                Accessible.description: I18n.tr("Session state, notifications and sounds")
            }
        }

        Shortcut { sequences: ["Ctrl+Tab"]; onActivated: configTabBar.currentIndex = (configTabBar.currentIndex + 1) % configTabBar.count }
        Shortcut { sequences: ["Ctrl+Shift+Tab"]; onActivated: configTabBar.currentIndex = (configTabBar.currentIndex + configTabBar.count - 1) % configTabBar.count }

        StackLayout {
            id: configStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: configTabBar.currentIndex

            // Aba Geral: valores editados vivem nas propriedades cfg_* da raiz; o StackLayout mantém todas as abas instanciadas
            QQC2.ScrollView {
                id: tabGeralScroll
                objectName: "tabGeral"
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    width: tabGeralScroll.availableWidth
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        color: configRoot.secondaryText
                        text: I18n.tr("Alerts, hiding and notifications are applied right away by the collector with their own Apply button; every other option is saved when you press OK.")
                    }

                        // Intervalo de Atualização por provedor (mínimo de 60 s); Flow: quebra de linha em largura estreita
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Refresh every (s):")
                            }

                            Repeater {
                                model: [
                                    { key: "cfg_refreshIntervalClaude", name: "Claude" },
                                    { key: "cfg_refreshIntervalCodex", name: "Codex" },
                                    { key: "cfg_refreshIntervalGemini", name: "Gemini" }
                                ]
                                delegate: RowLayout {
                                    required property var modelData
                                    spacing: Kirigami.Units.smallSpacing

                                    QQC2.Label {
                                        textFormat: Text.PlainText
                                        text: modelData.name
                                    }

                                    QQC2.SpinBox {
                                        from: 60
                                        to: 86400
                                        stepSize: 60
                                        editable: true
                                        value: configRoot[modelData.key]
                                        onValueModified: configRoot[modelData.key] = value
                                        QQC2.ToolTip.text: I18n.tr("%1 refresh interval in seconds (minimum 60)", modelData.name)
                                        QQC2.ToolTip.visible: hovered
                                    }
                                }
                            }
                        }

                        // Alertas: cor por ritmo de uso (padrão) ou por limiares fixos
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Alert by:")
                            }

                            QQC2.ComboBox {
                                id: alertModeCombo
                                textRole: "text"
                                valueRole: "value"
                                model: [
                                    { value: "pace", text: I18n.tr("Usage pace") },
                                    { value: "threshold", text: I18n.tr("Fixed threshold") }
                                ]
                                currentIndex: configRoot.alertMode === "threshold" ? 1 : 0
                                onActivated: { configRoot.alertMode = currentValue; configRoot.alertsDirty = true; }
                                Accessible.name: I18n.tr("Alert mode")
                            }

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Warning (%):")
                                enabled: configRoot.alertMode === "threshold"
                            }

                            QQC2.SpinBox {
                                from: 1
                                to: 99
                                editable: true
                                enabled: configRoot.alertMode === "threshold"
                                value: configRoot.alertWarning
                                onValueModified: { configRoot.alertWarning = value; configRoot.alertsDirty = true; }
                                Accessible.name: I18n.tr("Warning threshold in percent")
                            }

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Critical (%):")
                                enabled: configRoot.alertMode === "threshold"
                            }

                            QQC2.SpinBox {
                                from: 2
                                to: 100
                                editable: true
                                enabled: configRoot.alertMode === "threshold"
                                value: configRoot.alertCritical
                                onValueModified: { configRoot.alertCritical = value; configRoot.alertsDirty = true; }
                                Accessible.name: I18n.tr("Critical threshold in percent")
                            }

                            PlasmaComponents3.Button {
                                text: I18n.tr("Apply alerts")
                                icon.name: "dialog-ok-apply"
                                enabled: !configRoot.isBusy && !configRoot.isSavingAlerts
                                onClicked: configRoot.saveAlertSettings()
                            }

                            QQC2.Label {
                                visible: configRoot.alertsDirty
                                textFormat: Text.PlainText
                                color: Kirigami.Theme.neutralTextColor
                                text: I18n.tr("Not applied yet")
                            }
                        }

                        // Ocultar quando a CLI não está rodando (desligado por padrão)
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                text: I18n.tr("Hide without the CLI running:")
                                textFormat: Text.PlainText
                            }

                            QQC2.ComboBox {
                                textRole: "text"
                                valueRole: "value"
                                model: [
                                    { value: "off", text: I18n.tr("Never") },
                                    { value: "provider", text: I18n.tr("Only the stopped provider") },
                                    { value: "widget", text: I18n.tr("The whole widget") }
                                ]
                                currentIndex: configRoot.hideMode === "widget" ? 2 : (configRoot.hideMode === "provider" ? 1 : 0)
                                onActivated: { configRoot.hideMode = currentValue; configRoot.hideDirty = true; }
                                Accessible.name: I18n.tr("Hide when the CLI process is not running")
                                Accessible.description: I18n.tr("The whole widget reappears when you open the popup or the settings; a thin sliver with the right-click menu remains in the panel")
                                QQC2.ToolTip.text: Accessible.description
                                QQC2.ToolTip.visible: hovered || activeFocus
                            }

                            PlasmaComponents3.Button {
                                text: I18n.tr("Apply hiding")
                                icon.name: "dialog-ok-apply"
                                enabled: !configRoot.isBusy && !configRoot.isSavingHide
                                onClicked: configRoot.saveHideSettings()
                            }

                            QQC2.Label {
                                visible: configRoot.hideDirty
                                textFormat: Text.PlainText
                                color: Kirigami.Theme.neutralTextColor
                                text: I18n.tr("Not applied yet")
                            }

                            QQC2.Label {
                                width: parent.width
                                wrapMode: Text.WordWrap
                                color: configRoot.secondaryText
                                textFormat: Text.PlainText
                                text: I18n.tr("To find the hidden widget again: point at the thin sliver in the panel (it reopens the monitor and right-click leads to Configure), use the panel edit mode, or open the hidden items in the system tray. The widget never disappears while the popup or this window is open.")
                            }
                        }

                        // Atualizações: uma consulta por dia ao GitHub Releases e ao npm (sem credenciais; nada é baixado)
                        QQC2.CheckBox {
                            id: updateCheckBox
                            text: I18n.tr("Check for new versions once a day")
                            checked: configRoot.updateCheck
                            enabled: !configRoot.isBusy && !configRoot.isSavingUpdates
                            onToggled: { configRoot.updateCheck = checked; configRoot.saveUpdateSetting(checked); }
                            Accessible.description: I18n.tr("Queries the widget's GitHub Releases and the npm registry for Claude Code, Codex and Gemini CLI; nothing is downloaded or installed")
                            QQC2.ToolTip.text: Accessible.description
                            QQC2.ToolTip.visible: hovered || activeFocus
                        }

                        // Último recurso para achar o coletor (PATH, ~/.local/bin e pipx vêm antes)
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Collector path:")
                            }

                            QQC2.TextField {
                                objectName: "collectorPathField"
                                Layout.fillWidth: true
                                text: configRoot.cfg_collectorPath
                                placeholderText: I18n.tr("Empty = ai-usage-collector from the PATH")
                                onTextEdited: configRoot.cfg_collectorPath = text
                                Accessible.name: I18n.tr("Path to the ai-usage-collector executable")
                                Accessible.description: I18n.tr("Only used when the collector is not on the PATH, in ~/.local/bin or in pipx; accepts ~/")
                                QQC2.ToolTip.text: Accessible.description
                                QQC2.ToolTip.visible: hovered || activeFocus
                            }
                        }
                }
            }

            // Aba Painel: valores editados vivem nas propriedades cfg_* da raiz; o StackLayout mantém todas as abas instanciadas
            QQC2.ScrollView {
                id: tabPainelScroll
                objectName: "tabPainel"
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    width: tabPainelScroll.availableWidth
                    spacing: Kirigami.Units.smallSpacing

                        // Notch compacto: cor de destaque, visibilidade e ordem dos provedores
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Accent color:")
                            }

                            QQC2.ComboBox {
                                id: accentCombo
                                textRole: "name"
                                valueRole: "key"
                                model: [
                                    { key: "plasma", name: I18n.tr("Plasma highlight") },
                                    { key: "pink", name: I18n.tr("Pink") },
                                    { key: "red", name: I18n.tr("Red") },
                                    { key: "orange", name: I18n.tr("Orange") },
                                    { key: "yellow", name: I18n.tr("Yellow") },
                                    { key: "green", name: I18n.tr("Green") },
                                    { key: "teal", name: I18n.tr("Teal") },
                                    { key: "blue", name: I18n.tr("Blue") },
                                    { key: "indigo", name: I18n.tr("Indigo") },
                                    { key: "purple", name: I18n.tr("Purple") },
                                    { key: "white", name: I18n.tr("White") },
                                    { key: "off", name: I18n.tr("Off") }
                                ]
                                currentIndex: Math.max(0, indexOfValue(configRoot.cfg_accentPreset))
                                onActivated: configRoot.cfg_accentPreset = currentValue
                                Accessible.name: I18n.tr("Notch accent color")
                            }

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("Providers in the panel:")
                            }

                            Repeater {
                                model: configRoot.providerOrderList
                                delegate: RowLayout {
                                    required property string modelData
                                    required property int index
                                    spacing: 0

                                    QQC2.CheckBox {
                                        text: Presets.providerInfo(modelData).name
                                        checked: configRoot.cfg_hiddenProviders.split(",").indexOf(modelData) === -1
                                        onToggled: configRoot.setProviderHidden(modelData, !checked)
                                    }
                                    QQC2.ToolButton {
                                        icon.name: "go-previous"
                                        enabled: index > 0
                                        onClicked: configRoot.moveProvider(index, -1)
                                        Accessible.name: I18n.tr("Move %1 earlier", Presets.providerInfo(modelData).name)
                                    }
                                    QQC2.ToolButton {
                                        icon.name: "go-next"
                                        enabled: index < configRoot.providerOrderList.length - 1
                                        onClicked: configRoot.moveProvider(index, 1)
                                        Accessible.name: I18n.tr("Move %1 later", Presets.providerInfo(modelData).name)
                                    }
                                }
                            }
                        }

                        // Notch flutuante (opcional): janela própria presa a uma borda da tela, independente do painel
                        ColumnLayout {
                            objectName: "floatingSection"
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.CheckBox {
                                objectName: "floatingToggle"
                                text: I18n.tr("Floating Notch (own window on a screen edge)")
                                checked: configRoot.floatNow.enabled
                                onToggled: configRoot.cfg_floatingNotch = checked
                                Accessible.name: I18n.tr("Show the Notch as a floating window pinned to a screen edge")
                                Accessible.description: I18n.tr("Off by default. When on, the widget in the panel becomes a small marker (right-click it to configure) and the Notch lives in its own window")
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing
                                enabled: configRoot.floatNow.enabled

                                QQC2.Label {
                                    text: I18n.tr("Edge:")
                                    textFormat: Text.PlainText
                                }
                                QQC2.ComboBox {
                                    objectName: "floatEdgeCombo"
                                    textRole: "name"
                                    valueRole: "key"
                                    model: [
                                        { key: "top", name: I18n.tr("Top") },
                                        { key: "bottom", name: I18n.tr("Bottom") },
                                        { key: "left", name: I18n.tr("Left") },
                                        { key: "right", name: I18n.tr("Right") }
                                    ]
                                    currentIndex: Math.max(0, indexOfValue(configRoot.floatNow.edge))
                                    onActivated: configRoot.cfg_floatEdge = currentValue
                                    Accessible.name: I18n.tr("Screen edge of the floating Notch")
                                }

                                QQC2.Label {
                                    text: I18n.tr("Size (%):")
                                    textFormat: Text.PlainText
                                }
                                QQC2.SpinBox {
                                    objectName: "floatSizeSpin"
                                    from: 80
                                    to: 160
                                    stepSize: 10
                                    editable: true
                                    value: Math.round(configRoot.floatNow.scale * 100)
                                    onValueModified: configRoot.cfg_floatSize = value
                                    Accessible.name: I18n.tr("Floating Notch size in percent (80 to 160)")
                                }

                                QQC2.Label {
                                    text: I18n.tr("Screen:")
                                    textFormat: Text.PlainText
                                }
                                QQC2.ComboBox {
                                    objectName: "floatScreenCombo"
                                    textRole: "name"
                                    valueRole: "key"
                                    model: [{ key: "", name: I18n.tr("Screen of the widget") }].concat(Qt.application.screens.map(function (s) { return { key: s.name, name: s.name }; }))
                                    currentIndex: Math.max(0, indexOfValue(configRoot.floatNow.screen))
                                    onActivated: configRoot.cfg_floatScreen = currentValue
                                    Accessible.name: I18n.tr("Screen of the floating Notch")
                                }

                                QQC2.Label {
                                    text: I18n.tr("Position (px from the center):")
                                    textFormat: Text.PlainText
                                }
                                // Padrão dos SpinBox desta aba: `value` lido da config validada, onValueModified grava o cfg_*; este
                                // mostra a posição da borda escolhida (uma por borda) e aceita -20000..20000 px (a janela reclampa)
                                QQC2.SpinBox {
                                    objectName: "floatOffsetSpin"
                                    from: -20000
                                    to: 20000
                                    stepSize: 10
                                    editable: true
                                    value: ({ top: configRoot.cfg_floatOffsetTop, bottom: configRoot.cfg_floatOffsetBottom,
                                              left: configRoot.cfg_floatOffsetLeft, right: configRoot.cfg_floatOffsetRight })[configRoot.floatNow.edge]
                                    onValueModified: configRoot.setFloatOffset(configRoot.floatNow.edge, value)
                                    Accessible.name: I18n.tr("Floating Notch position along the edge, in pixels from the center (remembered for each edge)")
                                }
                                QQC2.Button {
                                    objectName: "floatRecenter"
                                    text: I18n.tr("Center")
                                    icon.name: "zoom-fit-best"
                                    onClicked: configRoot.setFloatOffset(configRoot.floatNow.edge, 0)
                                    Accessible.name: I18n.tr("Center the floating Notch on this edge")
                                }

                                QQC2.CheckBox {
                                    objectName: "floatSnapCheck"
                                    text: I18n.tr("Snap to the center when dragging")
                                    checked: configRoot.floatNow.snap
                                    onToggled: configRoot.cfg_floatSnap = checked
                                    Accessible.name: I18n.tr("Snap the floating Notch to the center of the edge when dragging")
                                }
                            }

                            QQC2.Label {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                textFormat: Text.PlainText
                                text: I18n.tr("Drag the floating Notch along the edge (or use the arrow keys; Home centers it); the position is remembered for each edge. Wayland (KDE Plasma): uses the layer-shell protocol, so panels appearing or disappearing never move it. X11: a plain always-on-top window without reserved area. If the layer-shell QML module is missing the option has no effect and the Notch stays in the panel; other compositors without layer-shell may show a regular window. Only for a widget in a panel (not on the desktop). With a specific screen, only the widget in a panel of that screen floats; two widgets on the same screen overlap, so enable it in one. Right-click the floating Notch for Configure.")
                            }
                        }

                        // Estilo do painel: Pílula (padrão), Ring, Text e Bar; modo e centro do anel; tamanho e margem
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                text: I18n.tr("Panel style:")
                                textFormat: Text.PlainText
                            }
                            QQC2.ComboBox {
                                textRole: "name"
                                valueRole: "key"
                                model: [
                                    { key: "pill", name: I18n.tr("Pill") },
                                    { key: "ring", name: I18n.tr("Ring") },
                                    { key: "text", name: I18n.tr("Text (% and dot)") },
                                    { key: "bar", name: I18n.tr("Bar (bars)") }
                                ]
                                currentIndex: Math.max(0, indexOfValue(configRoot.panelNow.style))
                                onActivated: configRoot.cfg_panelStyle = currentValue
                                Accessible.name: I18n.tr("Panel style")
                                Accessible.description: I18n.tr("Pill: dark capsule with rings. Ring: loose rings. Text: percentage and level dot. Bar: vertical bars with a time marker")
                            }

                            QQC2.Label {
                                text: I18n.tr("Show:")
                                textFormat: Text.PlainText
                            }
                            QQC2.ComboBox {
                                textRole: "name"
                                valueRole: "key"
                                model: [
                                    { key: "ring", name: I18n.tr("Chart only") },
                                    { key: "ringpct", name: I18n.tr("Chart and %") },
                                    { key: "pct", name: I18n.tr("% only") }
                                ]
                                currentIndex: Math.max(0, indexOfValue(configRoot.panelNow.mode))
                                onActivated: configRoot.cfg_panelMode = currentValue
                                Accessible.name: I18n.tr("Panel display mode")
                            }

                            QQC2.Label {
                                text: I18n.tr("Ring center:")
                                textFormat: Text.PlainText
                            }
                            QQC2.ComboBox {
                                textRole: "name"
                                valueRole: "key"
                                model: [
                                    { key: "logo", name: I18n.tr("Logo") },
                                    { key: "pct", name: I18n.tr("%") },
                                    { key: "logopct", name: I18n.tr("Logo and %") }
                                ]
                                currentIndex: Math.max(0, indexOfValue(configRoot.panelNow.center))
                                onActivated: configRoot.cfg_ringCenter = currentValue
                                Accessible.name: I18n.tr("Ring center")
                                Accessible.description: I18n.tr("With % in the center the ring grows to 28 px; in thin panels it goes back to the logo")
                            }

                            QQC2.Label {
                                text: I18n.tr("Size (%):")
                                textFormat: Text.PlainText
                            }
                            QQC2.SpinBox {
                                from: 80
                                to: 160
                                stepSize: 10
                                editable: true
                                value: Math.round(configRoot.panelNow.scale * 100)
                                onValueModified: configRoot.cfg_metricSize = value
                                Accessible.name: I18n.tr("Metrics size in percent (80 to 160)")
                                QQC2.ToolTip.text: I18n.tr("80 to 160. The panel limits the size to its thickness, without clipping")
                                QQC2.ToolTip.visible: hovered || activeFocus
                            }

                            QQC2.CheckBox {
                                text: I18n.tr("Automatic margin")
                                checked: configRoot.panelNow.margin < 0
                                onToggled: configRoot.cfg_panelMargin = checked ? -1 : Kirigami.Units.smallSpacing
                                Accessible.name: I18n.tr("Automatic inner margin of the panel")
                            }
                            QQC2.SpinBox {
                                from: 0
                                to: 16
                                editable: true
                                enabled: configRoot.panelNow.margin >= 0
                                value: Math.max(0, configRoot.panelNow.margin)
                                onValueModified: configRoot.cfg_panelMargin = value
                                Accessible.name: I18n.tr("Inner margin of the panel in pixels (0 to 16)")
                            }

                            QQC2.Label {
                                width: parent.width
                                wrapMode: Text.WordWrap
                                textFormat: Text.PlainText
                                text: I18n.tr("Bar in a vertical panel needs about 40 px of width: narrower than that, the panel uses Text or Pill instead of clipping. In the Text style, \"Chart only\" counts as \"Chart and %\". With % in the center, the ring grows to 28 px (in thin panels it goes back to the logo).")
                            }
                        }
                }
            }

            // Aba Popup: valores editados vivem nas propriedades cfg_* da raiz; o StackLayout mantém todas as abas instanciadas
            QQC2.ScrollView {
                id: tabPopupScroll
                objectName: "tabPopup"
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    width: tabPopupScroll.availableWidth
                    spacing: Kirigami.Units.smallSpacing

                        QQC2.CheckBox {
                            text: I18n.tr("Open the popup on mouse hover (off: click only)")
                            checked: configRoot.cfg_hoverOpen
                            onToggled: configRoot.cfg_hoverOpen = checked
                        }

                        // Popup: usado/restante e contagem/data (valem no popup, na dica e no painel), opacidade, cards
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                text: I18n.tr("Popup:")
                                textFormat: Text.PlainText
                            }
                            QQC2.ComboBox {
                                textRole: "name"
                                valueRole: "key"
                                model: [
                                    { key: "used", name: I18n.tr("Show used") },
                                    { key: "remaining", name: I18n.tr("Show remaining") }
                                ]
                                currentIndex: configRoot.viewNow.remaining ? 1 : 0
                                onActivated: configRoot.cfg_usageDisplay = currentValue
                                Accessible.name: I18n.tr("Displayed values: used or remaining")
                                Accessible.description: I18n.tr("Applies to the popup, the tooltip and the panel; notifications do not change")
                            }
                            QQC2.ComboBox {
                                textRole: "name"
                                valueRole: "key"
                                model: [
                                    { key: "countdown", name: I18n.tr("Release as countdown") },
                                    { key: "date", name: I18n.tr("Release as date and time") }
                                ]
                                currentIndex: configRoot.viewNow.date ? 1 : 0
                                onActivated: configRoot.cfg_resetDisplay = currentValue
                                Accessible.name: I18n.tr("Release shown as a countdown or as date and time")
                            }
                            QQC2.Label {
                                text: I18n.tr("Background opacity (%):")
                                textFormat: Text.PlainText
                            }
                            QQC2.SpinBox {
                                from: 80
                                to: 100
                                stepSize: 5
                                editable: true
                                value: Math.round(configRoot.viewNow.opacity * 100)
                                onValueModified: configRoot.cfg_popupOpacity = value
                                Accessible.name: I18n.tr("Popup background opacity in percent (80 to 100)")
                            }
                            QQC2.Label {
                                text: I18n.tr("Providers in the popup:")
                                textFormat: Text.PlainText
                            }
                            Repeater {
                                model: configRoot.popupOrderList
                                delegate: RowLayout {
                                    required property string modelData
                                    required property int index
                                    spacing: 0

                                    QQC2.CheckBox {
                                        text: Presets.providerInfo(modelData).name
                                        checked: configRoot.cfg_popupHiddenProviders.split(",").indexOf(modelData) === -1
                                        onToggled: configRoot.setPopupProviderHidden(modelData, !checked)
                                    }
                                    QQC2.ToolButton {
                                        icon.name: "go-previous"
                                        enabled: index > 0
                                        onClicked: configRoot.movePopupProvider(index, -1)
                                        Accessible.name: I18n.tr("Move %1 earlier in the popup", Presets.providerInfo(modelData).name)
                                    }
                                    QQC2.ToolButton {
                                        icon.name: "go-next"
                                        enabled: index < configRoot.popupOrderList.length - 1
                                        onClicked: configRoot.movePopupProvider(index, 1)
                                        Accessible.name: I18n.tr("Move %1 later in the popup", Presets.providerInfo(modelData).name)
                                    }
                                }
                            }
                        }
                }
            }

            // Aba Contas
            ColumnLayout {
                objectName: "tabContas"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    text: I18n.tr("View the registered Claude, Codex and Gemini accounts and manage their lifecycle directly.")
                    color: configRoot.secondaryText
                    wrapMode: Text.WordWrap
                }

                // Seção expansível: Adicionar Nova Conta
                Kirigami.AbstractCard {
                    id: addAccountSection
                    Layout.fillWidth: true

                    contentItem: ColumnLayout {
                        spacing: Kirigami.Units.smallSpacing

                        // Cabeçalho retrátil: o botão Expandir/Recolher é o controle (teclado e leitor de tela)
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            Kirigami.Icon {
                                source: configRoot.isAddFormExpanded ? "list-remove" : "list-add"
                                implicitWidth: Kirigami.Units.iconSizes.small
                                implicitHeight: Kirigami.Units.iconSizes.small
                            }

                            QQC2.Label {
                                textFormat: Text.PlainText
                                text: I18n.tr("+ Add New Account")
                                font.bold: true
                                font.pointSize: Kirigami.Theme.defaultFont.pointSize
                                Layout.fillWidth: true
                            }

                            PlasmaComponents3.Button {
                                id: toggleAddFormBtn
                                Accessible.name: I18n.tr("Add New Account")
                                Accessible.description: configRoot.isAddFormExpanded ? I18n.tr("Collapse") : I18n.tr("Expand")
                                text: configRoot.isAddFormExpanded ? I18n.tr("Collapse") : I18n.tr("Expand")
                                icon.name: configRoot.isAddFormExpanded ? "arrow-up" : "arrow-down"
                                display: QQC2.AbstractButton.TextBesideIcon
                                onClicked: {
                                    configRoot.isAddFormExpanded = !configRoot.isAddFormExpanded;
                                }
                            }
                        }

                        // Formulário de adição (visível apenas quando expandido)
                        ColumnLayout {
                            id: addAccountFormLayout
                            Layout.fillWidth: true
                            visible: configRoot.isAddFormExpanded
                            spacing: Kirigami.Units.smallSpacing

                            Kirigami.Separator {
                                Layout.fillWidth: true
                            }

                            // Campo 1: Seleção do Provedor
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing

                                QQC2.Label {
                                    textFormat: Text.PlainText
                                    text: I18n.tr("Provider:")
                                    Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                                    font.bold: true
                                }

                                Rectangle {
                                    id: providerIndicator
                                    implicitWidth: Math.round(Kirigami.Units.gridUnit * 0.75)
                                    implicitHeight: Math.round(Kirigami.Units.gridUnit * 0.75)
                                    radius: width / 2
                                    color: configRoot.getProviderColor(providerComboBox.currentText)
                                    Layout.alignment: Qt.AlignVCenter
                                    border.width: 1
                                    border.color: Qt.rgba(0, 0, 0, 0.15)
                                }

                                PlasmaComponents3.ComboBox {
                                    id: providerComboBox
                                    Layout.fillWidth: true
                                    Accessible.name: I18n.tr("Provider:")
                                    model: ["Claude", "Codex", "Gemini"]
                                    currentIndex: 0
                                    enabled: !configRoot.isBusy
                                }
                            }

                            // Campo 2: Apelido / Nome da Conta
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing

                                QQC2.Label {
                                    textFormat: Text.PlainText
                                    text: I18n.tr("Nickname:")
                                    Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                                    font.bold: true
                                }

                                QQC2.TextField {
                                    id: accountNameField
                                    Layout.fillWidth: true
                                    Accessible.name: I18n.tr("Nickname:")
                                    placeholderText: I18n.tr("E.g. Claude Work, Codex Personal (optional)")
                                    enabled: !configRoot.isBusy
                                }
                            }

                            // Ações Rápidas: Captura Direta e Login no Terminal
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.topMargin: Kirigami.Units.smallSpacing
                                spacing: Kirigami.Units.smallSpacing

                                PlasmaComponents3.Button {
                                    id: captureCurrentAccountBtn
                                    text: I18n.tr("Capture Current CLI Login")
                                    icon.name: "document-import"
                                    highlighted: true
                                    enabled: !configRoot.isBusy
                                    QQC2.ToolTip.text: I18n.tr("Detects and imports the session currently active on the system for %1 without typing any paths", providerComboBox.currentText)
                                    QQC2.ToolTip.visible: hovered
                                    onClicked: {
                                        configRoot.captureCurrentAccount();
                                    }
                                }

                                PlasmaComponents3.Button {
                                    id: interactiveLoginAccountBtn
                                    text: I18n.tr("Log In in the Terminal...")
                                    icon.name: "utilities-terminal"
                                    enabled: !configRoot.isBusy
                                    QQC2.ToolTip.text: I18n.tr("Opens an isolated terminal to authenticate a new %1 account without overwriting the main login", providerComboBox.currentText)
                                    QQC2.ToolTip.visible: hovered
                                    onClicked: {
                                        configRoot.interactiveLoginAccount();
                                    }
                                }

                                Item {
                                    Layout.fillWidth: true
                                }
                            }

                            // Subseção retrátil: Opções Avançadas (Configuração Manual)
                            Kirigami.Separator {
                                Layout.fillWidth: true
                                Layout.topMargin: Kirigami.Units.smallSpacing
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing

                                Kirigami.Icon {
                                    source: configRoot.isAdvancedExpanded ? "arrow-up" : "arrow-down"
                                    implicitWidth: Kirigami.Units.iconSizes.small
                                    implicitHeight: Kirigami.Units.iconSizes.small
                                }

                                QQC2.Label {
                                    textFormat: Text.PlainText
                                    text: I18n.tr("Advanced Options (Manual Setup)")
                                    font.bold: false
                                    color: configRoot.secondaryText
                                    Layout.fillWidth: true
                                }

                                PlasmaComponents3.Button {
                                    id: toggleAdvancedBtn
                                    text: configRoot.isAdvancedExpanded ? I18n.tr("Hide") : I18n.tr("Set Up Manually")
                                    icon.name: configRoot.isAdvancedExpanded ? "arrow-up" : "arrow-down"
                                    display: QQC2.AbstractButton.TextBesideIcon
                                    onClicked: {
                                        configRoot.isAdvancedExpanded = !configRoot.isAdvancedExpanded;
                                    }
                                }
                            }

                            ColumnLayout {
                                id: advancedFieldsLayout
                                Layout.fillWidth: true
                                visible: configRoot.isAdvancedExpanded
                                spacing: Kirigami.Units.smallSpacing

                                // Campo: Caminho das Credenciais / Diretório
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Kirigami.Units.smallSpacing

                                    QQC2.Label {
                                        textFormat: Text.PlainText
                                        text: I18n.tr("Path:")
                                        Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                                        font.bold: true
                                    }

                                    QQC2.TextField {
                                        id: credentialPathField
                                        Layout.fillWidth: true
                                        Accessible.name: I18n.tr("Path:")
                                        placeholderText: I18n.tr("E.g. %1", configRoot.getDefaultPath(providerComboBox.currentText))
                                        enabled: !configRoot.isBusy
                                    }

                                    PlasmaComponents3.Button {
                                        id: useDefaultPathBtn
                                        text: I18n.tr("Use Default Path")
                                        icon.name: "document-open"
                                        enabled: !configRoot.isBusy
                                        QQC2.ToolTip.text: I18n.tr("Fill in with the default directory '%1'", configRoot.getDefaultPath(providerComboBox.currentText))
                                        QQC2.ToolTip.visible: hovered
                                        onClicked: {
                                            credentialPathField.text = configRoot.getDefaultPath(providerComboBox.currentText);
                                        }
                                    }
                                }

                                // Campo: Link de Convite Opcional
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Kirigami.Units.smallSpacing

                                    QQC2.Label {
                                        textFormat: Text.PlainText
                                        text: I18n.tr("Invite Link:")
                                        Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                                    }

                                    QQC2.TextField {
                                        id: inviteUrlField
                                        Layout.fillWidth: true
                                        Accessible.name: I18n.tr("Invite Link:")
                                        placeholderText: I18n.tr("https://... (optional)")
                                        enabled: !configRoot.isBusy
                                    }
                                }

                                // Ações Manuais: Limpar e Salvar
                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.topMargin: Kirigami.Units.smallSpacing
                                    spacing: Kirigami.Units.smallSpacing

                                    Item {
                                        Layout.fillWidth: true
                                    }

                                    PlasmaComponents3.Button {
                                        id: clearFormBtn
                                        text: I18n.tr("Clear")
                                        icon.name: "edit-clear"
                                        enabled: !configRoot.isBusy
                                        onClicked: {
                                            configRoot.clearAddAccountForm();
                                        }
                                    }

                                    PlasmaComponents3.Button {
                                        id: saveAccountBtn
                                        text: I18n.tr("Save Manually")
                                        icon.name: "document-save"
                                        enabled: !configRoot.isBusy
                                        QQC2.ToolTip.text: I18n.tr("Save the account using the custom path entered manually")
                                        QQC2.ToolTip.visible: hovered
                                        onClicked: {
                                            configRoot.addAccount();
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Lista de Contas
                PlasmaComponents3.ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    contentItem: ListView {
                        id: accountsListView
                        spacing: Kirigami.Units.smallSpacing
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        model: configRoot.getAccountsList()

                        delegate: Kirigami.AbstractCard {
                            id: cardItem
                            width: accountsListView.width

                            contentItem: RowLayout {
                                spacing: Kirigami.Units.smallSpacing * 1.5

                                // Badge colorido do provedor
                                Rectangle {
                                    implicitWidth: providerTag.implicitWidth + Kirigami.Units.smallSpacing * 2
                                    implicitHeight: providerTag.implicitHeight + Kirigami.Units.smallSpacing
                                    radius: 4
                                    color: Qt.alpha(configRoot.getProviderColor(modelData.provider), 0.18)  // fundo suave + borda: o texto usa a cor do tema (>= 4,5:1)
                                    border.width: 1
                                    border.color: configRoot.getProviderColor(modelData.provider)

                                    QQC2.Label {
                                        textFormat: Text.PlainText
                                        id: providerTag
                                        anchors.centerIn: parent
                                        text: (modelData.provider || "").toUpperCase()
                                        font.bold: true
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                                        color: Kirigami.Theme.textColor
                                    }
                                }

                                // Informações da conta: Nome, ID e Saúde
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    RowLayout {
                                        spacing: Kirigami.Units.smallSpacing

                                        QQC2.Label {
                                            textFormat: Text.PlainText
                                            text: modelData.name || modelData.id
                                            font.bold: true
                                            font.pointSize: Kirigami.Theme.defaultFont.pointSize
                                            elide: Text.ElideRight
                                        }

                                        Rectangle {
                                            implicitWidth: healthText.implicitWidth + Kirigami.Units.smallSpacing * 2
                                            implicitHeight: healthText.implicitHeight + 2
                                            radius: 3
                                            readonly property color tone: configRoot.healthTone(modelData.healthStatus)
                                            color: Qt.alpha(tone, 0.18)  // palavra + cor; texto na cor do tema (>= 4,5:1 nos dois temas)
                                            border.width: 1
                                            border.color: tone

                                            QQC2.Label {
                                                textFormat: Text.PlainText
                                                id: healthText
                                                anchors.centerIn: parent
                                                text: {
                                                    if (modelData.healthStatus === "valid") return I18n.tr("Active");
                                                    if (modelData.healthStatus === "session_expired") return I18n.tr("Expired");
                                                    if (modelData.healthStatus === "not_configured") return I18n.tr("Not set up");
                                                    return modelData.healthStatus;
                                                }
                                                font.pointSize: Kirigami.Theme.smallFont.pointSize
                                                font.bold: true
                                                color: Kirigami.Theme.textColor
                                            }
                                        }
                                    }

                                    RowLayout {
                                        spacing: Kirigami.Units.smallSpacing

                                        QQC2.Label {
                                            textFormat: Text.PlainText
                                            text: I18n.tr("ID: %1", modelData.id)
                                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                                            color: configRoot.secondaryText
                                        }

                                        QQC2.Label {
                                            textFormat: Text.PlainText
                                            text: "•"
                                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                                            color: configRoot.secondaryText
                                        }

                                        QQC2.Label {
                                            textFormat: Text.PlainText
                                            text: modelData.source === "auto" ? I18n.tr("Automatic detection") : I18n.tr("Manual setup")
                                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                                            color: configRoot.secondaryText
                                        }
                                    }
                                }

                                // Botão de Renomear Conta
                                PlasmaComponents3.Button {
                                    id: renameAccountBtn
                                    icon.name: "document-edit"
                                    text: I18n.tr("Rename account")
                                    display: QQC2.AbstractButton.IconOnly
                                    enabled: !configRoot.isBusy

                                    QQC2.ToolTip.visible: hovered
                                    QQC2.ToolTip.text: I18n.tr("Rename account '%1'", modelData.name || modelData.id)

                                    onClicked: {
                                        configRoot.requestRenameAccount(modelData);
                                    }
                                }

                                // Botão de Excluir / Remover Conta
                                PlasmaComponents3.Button {
                                    id: deleteAccountBtn
                                    icon.name: "delete"
                                    text: I18n.tr("Remove account")
                                    display: QQC2.AbstractButton.IconOnly
                                    enabled: !configRoot.isBusy

                                    QQC2.ToolTip.visible: hovered
                                    QQC2.ToolTip.text: I18n.tr("Remove account '%1'", modelData.name || modelData.id)

                                    onClicked: {
                                        configRoot.requestDeleteAccount(modelData);
                                    }
                                }
                            }
                        }

                        // Placeholder se não houver contas
                        PlasmaExtras.PlaceholderMessage {
                            anchors.centerIn: parent
                            width: parent.width - Kirigami.Units.gridUnit * 2
                            visible: accountsListView.count === 0
                            iconName: "im-user-offline"
                            text: I18n.tr("No registered accounts")
                            explanation: I18n.tr("Run 'ai-usage-collector --refresh' to detect local credentials or add accounts in ~/.config/plasma-ai-usage/config.json")
                        }
                    }
                }

                // Perfis Órfãos: perfis em disco sem Conta cadastrada (nunca apagados sem confirmação)
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: configRoot.orphanProfiles.length > 0
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Heading {
                        textFormat: Text.PlainText
                        level: 4
                        text: I18n.tr("Orphan Profiles")
                    }

                    Repeater {
                        model: configRoot.orphanProfiles

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                textFormat: Text.PlainText
                                text: (modelData.provider || "").toUpperCase() + " · " + (modelData.email || modelData.id)
                            }

                            PlasmaComponents3.Button {
                                text: I18n.tr("Re-import")
                                enabled: !configRoot.isBusy
                                onClicked: configRoot.runOrphanAction("--reimport-orphan", modelData, false)
                            }

                            PlasmaComponents3.Button {
                                text: I18n.tr("Delete")
                                icon.name: "delete"
                                enabled: !configRoot.isBusy
                                onClicked: {
                                    configRoot.orphanPendingDeletion = modelData;
                                    orphanDeleteDialog.open();
                                }
                            }
                        }
                    }
                }
            }

            // Aba Notificações: valores editados vivem nas propriedades cfg_* da raiz; o StackLayout mantém todas as abas instanciadas
            QQC2.ScrollView {
                id: tabNotifScroll
                objectName: "tabNotif"
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    width: tabNotifScroll.availableWidth
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        color: configRoot.secondaryText
                        text: I18n.tr("Alerts, hiding and notifications are applied right away by the collector with their own Apply button; every other option is saved when you press OK.")
                    }

                        // Estado da Sessão do Claude Code e do Codex (ADR-0009): arco girando = ocupada, âmbar pulsando = aguardando
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.CheckBox {
                                text: I18n.tr("Show the session state (Claude and Codex)")
                                checked: configRoot.cfg_sessionState
                                onToggled: configRoot.cfg_sessionState = checked
                                Accessible.description: I18n.tr("Claude: ai-usage-collector --install-hooks (isolated profile: run it with each profile's CLAUDE_CONFIG_DIR). Codex: busy comes from the session logs without installing anything; ai-usage-collector --install-hooks codex (optional) ends the busy state at the end of each turn and is what enables the sound/Notch on Codex (without it Codex only shows the state). If the state does not update, reinstall the package: pip install -e .")
                                QQC2.ToolTip.text: I18n.tr("Claude: ai-usage-collector --install-hooks (isolated profile: run it with each profile's CLAUDE_CONFIG_DIR). Codex: busy comes from the session logs without installing anything; ai-usage-collector --install-hooks codex (optional) ends the busy state at the end of each turn and is what enables the sound/Notch on Codex (without it Codex only shows the state). If the state does not update, reinstall the package: pip install -e .")
                                QQC2.ToolTip.visible: hovered || activeFocus
                            }
                            QQC2.CheckBox {
                                text: I18n.tr("Open the Notch for 5 s when the session finishes or asks for something")
                                enabled: configRoot.cfg_sessionState
                                checked: configRoot.cfg_sessionAutoOpen
                                onToggled: configRoot.cfg_sessionAutoOpen = checked
                            }
                            QQC2.CheckBox {
                                text: I18n.tr("Play a sound at those moments")
                                enabled: configRoot.cfg_sessionState
                                checked: configRoot.cfg_sessionSound
                                onToggled: configRoot.cfg_sessionSound = checked
                            }
                        }

                        // Notificações do sistema: limiares, aviso antecipado, aviso de reset e silenciar por provedor
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            QQC2.Label {
                                text: I18n.tr("Notify at (%):")
                                textFormat: Text.PlainText
                            }

                            QQC2.SpinBox {
                                from: 1
                                to: 99
                                editable: true
                                value: configRoot.notifyWarning
                                onValueModified: { configRoot.notifyWarning = value; configRoot.notifyThresholdsEdited = true; configRoot.notifyDirty = true; }
                                Accessible.name: I18n.tr("Notify when this usage percentage is reached")
                            }

                            QQC2.Label {
                                text: I18n.tr("and at (%):")
                                textFormat: Text.PlainText
                            }

                            QQC2.SpinBox {
                                from: 2
                                to: 100
                                editable: true
                                value: configRoot.notifyCritical
                                onValueModified: { configRoot.notifyCritical = value; configRoot.notifyThresholdsEdited = true; configRoot.notifyDirty = true; }
                                Accessible.name: I18n.tr("Notify urgently when this usage percentage is reached")
                            }

                            QQC2.CheckBox {
                                text: I18n.tr("Warn before running out")
                                checked: configRoot.notifyEarly
                                onToggled: { configRoot.notifyEarly = checked; configRoot.notifyDirty = true; }
                                Accessible.description: I18n.tr("Native window: exhaustion forecast in 30 min; weekly: in 24 h (once per window)")
                                QQC2.ToolTip.text: Accessible.description
                                QQC2.ToolTip.visible: hovered || activeFocus
                            }

                            QQC2.CheckBox {
                                text: I18n.tr("Notify when the limit is released")
                                checked: configRoot.notifyReset
                                onToggled: { configRoot.notifyReset = checked; configRoot.notifyDirty = true; }
                                Accessible.description: I18n.tr("Only for limits that already triggered a warning")
                                QQC2.ToolTip.text: Accessible.description
                                QQC2.ToolTip.visible: hovered || activeFocus
                            }

                            QQC2.Label {
                                text: I18n.tr("Mute:")
                                textFormat: Text.PlainText
                            }

                            Repeater {
                                model: [
                                    { key: "claude", name: "Claude" },
                                    { key: "codex", name: "Codex" },
                                    { key: "gemini", name: "Gemini" }
                                ]
                                delegate: QQC2.CheckBox {
                                    required property var modelData
                                    text: modelData.name
                                    checked: configRoot.notifyMuted.indexOf(modelData.key) >= 0
                                    onToggled: configRoot.setProviderMuted(modelData.key, checked)
                                    Accessible.name: I18n.tr("Mute %1 notifications", modelData.name)
                                }
                            }

                            PlasmaComponents3.Button {
                                text: I18n.tr("Apply notifications")
                                icon.name: "dialog-ok-apply"
                                enabled: !configRoot.isBusy && !configRoot.isSavingNotify
                                onClicked: configRoot.saveNotifySettings()
                            }

                            QQC2.Label {
                                visible: configRoot.notifyDirty
                                textFormat: Text.PlainText
                                color: Kirigami.Theme.neutralTextColor
                                text: I18n.tr("Not applied yet")
                            }
                        }
                }
            }
        }
    }

    // Diálogo de confirmação de exclusão de Perfil Órfão
    QQC2.Dialog {
        id: orphanDeleteDialog
        title: I18n.tr("Delete Orphan Profile")
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                text: configRoot.orphanPendingDeletion
                    ? I18n.tr("Permanently delete the profile '%1' from disk? Its credentials will be erased.", configRoot.orphanPendingDeletion.id)
                    : ""
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.Button {
                    text: I18n.tr("Cancel")
                    onClicked: orphanDeleteDialog.close()
                }

                PlasmaComponents3.Button {
                    text: I18n.tr("Delete Profile")
                    icon.name: "delete"
                    highlighted: true
                    enabled: !configRoot.isBusy
                    onClicked: {
                        orphanDeleteDialog.close();
                        configRoot.runOrphanAction("--delete-orphan", configRoot.orphanPendingDeletion, true);
                    }
                }
            }
        }
    }

    // Diálogo nativo de confirmação de exclusão
    QQC2.Dialog {
        id: confirmDialog
        title: I18n.tr("Confirm Account Removal")
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                textFormat: Text.PlainText
                text: {
                    var acc = configRoot.accountPendingDeletion;
                    if (!acc) return "";
                    return I18n.tr(
                        "Do you really want to remove the account '%1' (ID: %2) from the provider %3?\n\nThis removes the account from the configuration file and updates the widget immediately.",
                        acc.name || acc.id,
                        acc.id,
                        (acc.provider || "").toUpperCase()
                    );
                }
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Item {
                    Layout.fillWidth: true
                }

                PlasmaComponents3.Button {
                    text: I18n.tr("Cancel")
                    onClicked: confirmDialog.close()
                }

                PlasmaComponents3.Button {
                    id: confirmDeleteButton
                    text: I18n.tr("Remove Account")
                    icon.name: "delete"
                    highlighted: true
                    enabled: !configRoot.isBusy
                    onClicked: {
                        confirmDialog.close();
                        configRoot.confirmDelete();
                    }
                }
            }
        }
    }

    // Diálogo nativo de renomeação de conta (sem standardButtons para compatibilidade com Breeze)
    QQC2.Dialog {
        id: renameDialog
        title: I18n.tr("Rename Account")
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                textFormat: Text.PlainText
                text: {
                    var acc = configRoot.accountPendingRename;
                    if (!acc) return "";
                    return I18n.tr(
                        "Enter the new name for the account '%1' (ID: %2) of the provider %3:",
                        acc.name || acc.id,
                        acc.id,
                        (acc.provider || "").toUpperCase()
                    );
                }
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            }

            QQC2.TextField {
                id: renameAccountField
                Layout.fillWidth: true
                Accessible.name: I18n.tr("New account name")
                placeholderText: I18n.tr("New account name")
                enabled: !configRoot.isBusy
                onAccepted: {
                    if (saveRenameButton.enabled) {
                        saveRenameButton.clicked();
                    }
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Item {
                    Layout.fillWidth: true
                }

                PlasmaComponents3.Button {
                    text: I18n.tr("Cancel")
                    onClicked: renameDialog.close()
                }

                PlasmaComponents3.Button {
                    id: saveRenameButton
                    text: I18n.tr("Save")
                    icon.name: "document-save"
                    highlighted: true
                    enabled: !configRoot.isBusy && (renameAccountField.text || "").trim().length > 0
                    onClicked: {
                        renameDialog.close();
                        configRoot.confirmRename();
                    }
                }
            }
        }
    }
}
