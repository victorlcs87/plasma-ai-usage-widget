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

Item {
    id: configRoot

    implicitWidth: Kirigami.Units.gridUnit * 32
    implicitHeight: Kirigami.Units.gridUnit * 28

    // Intervalo de Atualização por provedor (KConfigXT, main.xml)
    property int cfg_refreshIntervalClaude: 300
    property int cfg_refreshIntervalCodex: 300
    property int cfg_refreshIntervalGemini: 300

    // Notch compacto (KConfigXT): ordem, provedores ocultos e cor de destaque
    property string cfg_providerOrder: "claude,codex,gemini"
    property string cfg_hiddenProviders: ""
    property string cfg_accentPreset: "plasma"
    // Estado da Sessão (KConfigXT): os hooks só existem após `ai-usage-collector --install-hooks`
    property bool cfg_sessionState: false
    property bool cfg_sessionAutoOpen: true
    property bool cfg_sessionSound: false
    readonly property var providerOrderList: Presets.normalizeOrder(cfg_providerOrder)

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

    function safeI18n(text, arg1, arg2, arg3) {
        if (!text) return "";
        if (typeof i18n === "function") {
            if (arg3 !== undefined) return i18n(text, arg1, arg2, arg3);
            if (arg2 !== undefined) return i18n(text, arg1, arg2);
            if (arg1 !== undefined) return i18n(text, arg1);
            return i18n(text);
        }
        var res = text;
        if (arg1 !== undefined) res = res.replace("%1", arg1);
        if (arg2 !== undefined) res = res.replace("%2", arg2);
        if (arg3 !== undefined) res = res.replace("%3", arg3);
        return res;
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
            configRoot.errorMessage = configRoot.safeI18n("Por favor, preencha o apelido/nome da conta.");
            return;
        }
        if (!path) {
            configRoot.errorMessage = configRoot.safeI18n("Por favor, informe o caminho das credenciais ou diretório.");
            return;
        }

        configRoot.isAdding = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var safeArgs = shellQuote("--add-account") + " " +
                       shellQuote("--provider") + " " + shellQuote(prov) + " " +
                       shellQuote("--label") + " " + shellQuote(label) + " " +
                       shellQuote("--credential-path") + " " + shellQuote(path);

        if (inviteUrl.length > 0) {
            safeArgs += " " + shellQuote("--invite-url") + " " + shellQuote(inviteUrl);
        }
        safeArgs += " " + shellQuote("--status");

        var cmd = configRoot.buildCollectorCommand(safeArgs);
        additionDataSource.connectSource(cmd);
    }

    function captureCurrentAccount() {
        var prov = (providerComboBox.currentText || "Claude").toLowerCase().trim();
        var label = (accountNameField.text || "").trim();

        configRoot.isCapturing = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var safeArgs = shellQuote("--capture-current") + " " + shellQuote(prov);
        if (label.length > 0) {
            safeArgs += " " + shellQuote("--name") + " " + shellQuote(label);
        }
        safeArgs += " " + shellQuote("--status");

        var cmd = configRoot.buildCollectorCommand(safeArgs);
        captureDataSource.connectSource(cmd);
    }

    function interactiveLoginAccount() {
        var prov = (providerComboBox.currentText || "Claude").toLowerCase().trim();
        var label = (accountNameField.text || "").trim();

        configRoot.isInteractiveLogin = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var safeArgs = shellQuote("--interactive-login") + " " + shellQuote(prov);
        if (label.length > 0) {
            safeArgs += " " + shellQuote("--name") + " " + shellQuote(label);
        }
        safeArgs += " " + shellQuote("--status");

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
                    var nt = configRoot.statusData.notifications;
                    if (nt && !configRoot.isSavingNotify && !configRoot.notifyDirty) {
                        configRoot.notifyWarning = Math.round(Number(nt.warning)) || 80;
                        configRoot.notifyCritical = Math.round(Number(nt.critical)) || 95;
                        configRoot.notifyEarly = nt.early !== false;
                        configRoot.notifyReset = nt.reset === true;
                        configRoot.notifyMuted = Array.isArray(nt.muted) ? nt.muted : [];
                    }
                } catch (e) {
                    configRoot.errorMessage = configRoot.safeI18n("Erro ao ler dados de status: %1", e.message);
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
        var args = shellQuote("--set-alert-config") + " " + shellQuote("--alert-mode") + " " + shellQuote(configRoot.alertMode)
            + " " + shellQuote("--alert-warning") + " " + shellQuote(configRoot.alertWarning)
            + " " + shellQuote("--alert-critical") + " " + shellQuote(configRoot.alertCritical);
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
                configRoot.errorMessage = stderr || stdout || configRoot.safeI18n("Erro desconhecido");
            }
            disconnectSource(sourceName);
        }
    }

    // Notificações: o coletor valida (0 < aviso < crítico <= 100) e as envia pelo D-Bus
    function saveNotifySettings() {
        configRoot.isSavingNotify = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";
        var args = shellQuote("--set-notify-config");
        if (configRoot.notifyThresholdsEdited) {
            args += " " + shellQuote("--notify-warning") + " " + shellQuote(configRoot.notifyWarning)
                + " " + shellQuote("--notify-critical") + " " + shellQuote(configRoot.notifyCritical);
        }
        args += " " + shellQuote("--notify-early") + " " + shellQuote(configRoot.notifyEarly ? "on" : "off")
            + " " + shellQuote("--notify-reset") + " " + shellQuote(configRoot.notifyReset ? "on" : "off")
            + " " + shellQuote("--notify-mute") + " " + shellQuote(configRoot.notifyMuted.join(","));
        notifyDataSource.connectSource(configRoot.buildCollectorCommand(args));
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
                configRoot.errorMessage = stderr || stdout || configRoot.safeI18n("Erro desconhecido");
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
                configRoot.statusMessage = configRoot.safeI18n("Conta removida com sucesso!");
                configRoot.errorMessage = "";
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = configRoot.safeI18n("Falha ao remover conta: %1", stderr || stdout || configRoot.safeI18n("Erro desconhecido"));
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
        var args = shellQuote(flag) + " " + shellQuote(orphan.provider) + " " + shellQuote(orphan.id) + (confirm ? " " + shellQuote("--confirm") : "");
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
                configRoot.errorMessage = stderr || stdout || configRoot.safeI18n("Erro desconhecido");
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
                var msg = lines[0] || configRoot.safeI18n("Conta renomeada com sucesso!");
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
                configRoot.errorMessage = configRoot.safeI18n("Falha ao renomear conta: %1", stderr || stdout || configRoot.safeI18n("Erro desconhecido"));
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
                configRoot.statusMessage = configRoot.safeI18n("Conta adicionada com sucesso!");
                configRoot.errorMessage = "";
                configRoot.clearAddAccountForm();
                configRoot.loadStatus();
            } else {
                configRoot.errorMessage = configRoot.safeI18n("Falha ao adicionar conta: %1", stderr || stdout || configRoot.safeI18n("Erro desconhecido"));
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
                var msg = lines[0] || configRoot.safeI18n("Sessão ativa capturada com sucesso!");
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
                configRoot.errorMessage = configRoot.safeI18n("Falha ao capturar login atual: %1", stderr || stdout || configRoot.safeI18n("Erro desconhecido"));
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
                var msg = lines[0] || configRoot.safeI18n("Login interativo concluído com sucesso!");
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
                configRoot.errorMessage = configRoot.safeI18n("Falha no login interativo: %1", stderr || stdout || configRoot.safeI18n("Erro desconhecido"));
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
        var cmd = "cat " + shellQuote(statusFilePath) + " 2>/dev/null";
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
        var safeArgs = shellQuote("--remove-account") + " " + shellQuote(provClean) + " " + shellQuote(acc.id);
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
            configRoot.errorMessage = configRoot.safeI18n("O nome da conta não pode ser vazio.");
            return;
        }
        var acc = configRoot.accountPendingRename;
        configRoot.isRenaming = true;
        configRoot.statusMessage = "";
        configRoot.errorMessage = "";

        var provClean = String(acc.provider).toLowerCase().trim();
        var safeArgs = shellQuote("--rename-account") + " " +
                       shellQuote(provClean) + " " +
                       shellQuote(acc.id) + " " +
                       shellQuote("--label") + " " +
                       shellQuote(newName) + " " +
                       shellQuote("--status");
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
                level: 2
                text: configRoot.safeI18n("Gerenciamento de Contas de IA")
                Layout.fillWidth: true
            }

            PlasmaComponents3.Button {
                icon.name: "view-refresh"
                text: configRoot.safeI18n("Recarregar")
                display: QQC2.AbstractButton.IconOnly
                enabled: !configRoot.isBusy
                QQC2.ToolTip.text: configRoot.safeI18n("Atualizar lista de contas")
                QQC2.ToolTip.visible: hovered
                onClicked: {
                    configRoot.statusMessage = "";
                    configRoot.errorMessage = "";
                    configRoot.loadStatus();
                }
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            text: configRoot.safeI18n("Visualize as contas cadastradas de Claude, Codex e Gemini e gerencie o ciclo de vida diretamente.")
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
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

        // Notch compacto: cor de destaque, visibilidade e ordem dos provedores
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: configRoot.safeI18n("Cor de destaque:")
            }

            QQC2.ComboBox {
                id: accentCombo
                textRole: "name"
                valueRole: "key"
                model: Presets.accents
                currentIndex: Math.max(0, indexOfValue(configRoot.cfg_accentPreset))
                onActivated: configRoot.cfg_accentPreset = currentValue
                Accessible.name: configRoot.safeI18n("Cor de destaque do Notch")
            }

            QQC2.Label {
                text: configRoot.safeI18n("Provedores no painel:")
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
                        Accessible.name: configRoot.safeI18n("Mover %1 para antes", Presets.providerInfo(modelData).name)
                    }
                    QQC2.ToolButton {
                        icon.name: "go-next"
                        enabled: index < configRoot.providerOrderList.length - 1
                        onClicked: configRoot.moveProvider(index, 1)
                        Accessible.name: configRoot.safeI18n("Mover %1 para depois", Presets.providerInfo(modelData).name)
                    }
                }
            }
        }

        // Estado da Sessão do Claude Code (ADR-0009): arco girando = ocupada, âmbar pulsando = aguardando
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                text: configRoot.safeI18n("Mostrar o estado da sessão do Claude")
                checked: configRoot.cfg_sessionState
                onToggled: configRoot.cfg_sessionState = checked
                Accessible.description: configRoot.safeI18n("Requer instalar os hooks: ai-usage-collector --install-hooks")
                QQC2.ToolTip.text: configRoot.safeI18n("Requer instalar os hooks: ai-usage-collector --install-hooks")
                QQC2.ToolTip.visible: hovered || activeFocus
            }
            QQC2.CheckBox {
                text: configRoot.safeI18n("Abrir o Notch por 5 s quando a sessão terminar ou pedir algo")
                enabled: configRoot.cfg_sessionState
                checked: configRoot.cfg_sessionAutoOpen
                onToggled: configRoot.cfg_sessionAutoOpen = checked
            }
            QQC2.CheckBox {
                text: configRoot.safeI18n("Tocar um som nesses momentos")
                enabled: configRoot.cfg_sessionState
                checked: configRoot.cfg_sessionSound
                onToggled: configRoot.cfg_sessionSound = checked
            }
        }

        // Intervalo de Atualização por provedor (mínimo de 60 s)
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: configRoot.safeI18n("Atualizar a cada (s):")
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
                        text: modelData.name
                    }

                    QQC2.SpinBox {
                        from: 60
                        to: 86400
                        stepSize: 60
                        editable: true
                        value: configRoot[modelData.key]
                        onValueModified: configRoot[modelData.key] = value
                        QQC2.ToolTip.text: configRoot.safeI18n("Intervalo de Atualização do %1 em segundos (mínimo 60)", modelData.name)
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
                text: configRoot.safeI18n("Alerta por:")
            }

            QQC2.ComboBox {
                id: alertModeCombo
                textRole: "text"
                valueRole: "value"
                model: [
                    { value: "pace", text: configRoot.safeI18n("Ritmo de uso") },
                    { value: "threshold", text: configRoot.safeI18n("Limiar fixo") }
                ]
                currentIndex: configRoot.alertMode === "threshold" ? 1 : 0
                onActivated: { configRoot.alertMode = currentValue; configRoot.alertsDirty = true; }
                Accessible.name: configRoot.safeI18n("Modo de alerta")
            }

            QQC2.Label {
                text: configRoot.safeI18n("Aviso (%):")
                enabled: configRoot.alertMode === "threshold"
            }

            QQC2.SpinBox {
                from: 1
                to: 99
                editable: true
                enabled: configRoot.alertMode === "threshold"
                value: configRoot.alertWarning
                onValueModified: { configRoot.alertWarning = value; configRoot.alertsDirty = true; }
                Accessible.name: configRoot.safeI18n("Limiar de aviso em porcentagem")
            }

            QQC2.Label {
                text: configRoot.safeI18n("Crítico (%):")
                enabled: configRoot.alertMode === "threshold"
            }

            QQC2.SpinBox {
                from: 2
                to: 100
                editable: true
                enabled: configRoot.alertMode === "threshold"
                value: configRoot.alertCritical
                onValueModified: { configRoot.alertCritical = value; configRoot.alertsDirty = true; }
                Accessible.name: configRoot.safeI18n("Limiar crítico em porcentagem")
            }

            PlasmaComponents3.Button {
                text: configRoot.safeI18n("Aplicar")
                icon.name: "dialog-ok-apply"
                enabled: !configRoot.isBusy && !configRoot.isSavingAlerts
                onClicked: configRoot.saveAlertSettings()
            }
        }

        // Notificações do sistema: limiares, aviso antecipado, aviso de reset e silenciar por provedor
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: configRoot.safeI18n("Notificar em (%):")
                textFormat: Text.PlainText
            }

            QQC2.SpinBox {
                from: 1
                to: 99
                editable: true
                value: configRoot.notifyWarning
                onValueModified: { configRoot.notifyWarning = value; configRoot.notifyThresholdsEdited = true; configRoot.notifyDirty = true; }
                Accessible.name: configRoot.safeI18n("Notificar ao atingir esta porcentagem de uso")
            }

            QQC2.Label {
                text: configRoot.safeI18n("e em (%):")
                textFormat: Text.PlainText
            }

            QQC2.SpinBox {
                from: 2
                to: 100
                editable: true
                value: configRoot.notifyCritical
                onValueModified: { configRoot.notifyCritical = value; configRoot.notifyThresholdsEdited = true; configRoot.notifyDirty = true; }
                Accessible.name: configRoot.safeI18n("Notificar com urgência ao atingir esta porcentagem de uso")
            }

            QQC2.CheckBox {
                text: configRoot.safeI18n("Avisar antes de esgotar")
                checked: configRoot.notifyEarly
                onToggled: { configRoot.notifyEarly = checked; configRoot.notifyDirty = true; }
                Accessible.description: configRoot.safeI18n("Janela nativa: previsão de esgotamento em 30 min; semanal: em 24 h (uma vez por janela)")
                QQC2.ToolTip.text: Accessible.description
                QQC2.ToolTip.visible: hovered || activeFocus
            }

            QQC2.CheckBox {
                text: configRoot.safeI18n("Avisar quando o limite for liberado")
                checked: configRoot.notifyReset
                onToggled: { configRoot.notifyReset = checked; configRoot.notifyDirty = true; }
                Accessible.description: configRoot.safeI18n("Só para limites que já geraram aviso")
                QQC2.ToolTip.text: Accessible.description
                QQC2.ToolTip.visible: hovered || activeFocus
            }

            QQC2.Label {
                text: configRoot.safeI18n("Silenciar:")
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
                    Accessible.name: configRoot.safeI18n("Silenciar notificações do %1", modelData.name)
                }
            }

            PlasmaComponents3.Button {
                text: configRoot.safeI18n("Aplicar")
                icon.name: "dialog-ok-apply"
                enabled: !configRoot.isBusy && !configRoot.isSavingNotify
                onClicked: configRoot.saveNotifySettings()
            }
        }

        // Seção expansível: Adicionar Nova Conta
        Kirigami.AbstractCard {
            id: addAccountSection
            Layout.fillWidth: true

            contentItem: ColumnLayout {
                spacing: Kirigami.Units.smallSpacing

                // Cabeçalho retrátil clicável
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: configRoot.isAddFormExpanded ? "list-remove" : "list-add"
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: Kirigami.Units.iconSizes.small
                    }

                    QQC2.Label {
                        text: configRoot.safeI18n("+ Adicionar Nova Conta")
                        font.bold: true
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize
                        Layout.fillWidth: true

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                configRoot.isAddFormExpanded = !configRoot.isAddFormExpanded;
                            }
                        }
                    }

                    PlasmaComponents3.Button {
                        id: toggleAddFormBtn
                        text: configRoot.isAddFormExpanded ? configRoot.safeI18n("Recolher") : configRoot.safeI18n("Expandir")
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
                            text: configRoot.safeI18n("Provedor:")
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
                            text: configRoot.safeI18n("Apelido:")
                            Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                            font.bold: true
                        }

                        QQC2.TextField {
                            id: accountNameField
                            Layout.fillWidth: true
                            placeholderText: configRoot.safeI18n("Ex: Claude Trabalho, Codex Pessoal (opcional)")
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
                            text: configRoot.safeI18n("Capturar Login Atual do CLI")
                            icon.name: "document-import"
                            highlighted: true
                            enabled: !configRoot.isBusy
                            QQC2.ToolTip.text: configRoot.safeI18n("Detecta e importa a sessão ativa atual no sistema para %1 sem exigir digitação de caminhos", providerComboBox.currentText)
                            QQC2.ToolTip.visible: hovered
                            onClicked: {
                                configRoot.captureCurrentAccount();
                            }
                        }

                        PlasmaComponents3.Button {
                            id: interactiveLoginAccountBtn
                            text: configRoot.safeI18n("Fazer Login no Terminal...")
                            icon.name: "utilities-terminal"
                            enabled: !configRoot.isBusy
                            QQC2.ToolTip.text: configRoot.safeI18n("Abre terminal isolado para autenticar nova conta de %1 sem sobrescrever o login principal", providerComboBox.currentText)
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
                            text: configRoot.safeI18n("Opções Avançadas (Configuração Manual)")
                            font.bold: false
                            color: Kirigami.Theme.disabledTextColor
                            Layout.fillWidth: true

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    configRoot.isAdvancedExpanded = !configRoot.isAdvancedExpanded;
                                }
                            }
                        }

                        PlasmaComponents3.Button {
                            id: toggleAdvancedBtn
                            text: configRoot.isAdvancedExpanded ? configRoot.safeI18n("Ocultar") : configRoot.safeI18n("Configurar Manualmente")
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
                                text: configRoot.safeI18n("Caminho:")
                                Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                                font.bold: true
                            }

                            QQC2.TextField {
                                id: credentialPathField
                                Layout.fillWidth: true
                                placeholderText: configRoot.safeI18n("Ex: %1", configRoot.getDefaultPath(providerComboBox.currentText))
                                enabled: !configRoot.isBusy
                            }

                            PlasmaComponents3.Button {
                                id: useDefaultPathBtn
                                text: configRoot.safeI18n("Usar Caminho Padrão")
                                icon.name: "document-open"
                                enabled: !configRoot.isBusy
                                QQC2.ToolTip.text: configRoot.safeI18n("Preencher com o diretório padrão '%1'", configRoot.getDefaultPath(providerComboBox.currentText))
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
                                text: configRoot.safeI18n("Link de Convite:")
                                Layout.minimumWidth: Kirigami.Units.gridUnit * 7
                            }

                            QQC2.TextField {
                                id: inviteUrlField
                                Layout.fillWidth: true
                                placeholderText: configRoot.safeI18n("https://... (opcional)")
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
                                text: configRoot.safeI18n("Limpar")
                                icon.name: "edit-clear"
                                enabled: !configRoot.isBusy
                                onClicked: {
                                    configRoot.clearAddAccountForm();
                                }
                            }

                            PlasmaComponents3.Button {
                                id: saveAccountBtn
                                text: configRoot.safeI18n("Salvar Manualmente")
                                icon.name: "document-save"
                                enabled: !configRoot.isBusy
                                QQC2.ToolTip.text: configRoot.safeI18n("Salvar Conta informando o caminho customizado manualmente")
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
                            color: configRoot.getProviderColor(modelData.provider)

                            QQC2.Label {
                                id: providerTag
                                anchors.centerIn: parent
                                text: (modelData.provider || "").toUpperCase()
                                font.bold: true
                                font.pointSize: Kirigami.Theme.smallFont.pointSize
                                color: "white"
                            }
                        }

                        // Informações da conta: Nome, ID e Saúde
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            RowLayout {
                                spacing: Kirigami.Units.smallSpacing

                                QQC2.Label {
                                    text: modelData.name || modelData.id
                                    font.bold: true
                                    font.pointSize: Kirigami.Theme.defaultFont.pointSize
                                    elide: Text.ElideRight
                                }

                                Rectangle {
                                    implicitWidth: healthText.implicitWidth + Kirigami.Units.smallSpacing
                                    implicitHeight: healthText.implicitHeight + 2
                                    radius: 3
                                    color: {
                                        if (modelData.healthStatus === "valid") return "#27ae60";
                                        if (modelData.healthStatus === "session_expired") return "#f39c12";
                                        return "#7f8c8d";
                                    }

                                    QQC2.Label {
                                        id: healthText
                                        anchors.centerIn: parent
                                        text: {
                                            if (modelData.healthStatus === "valid") return configRoot.safeI18n("Ativa");
                                            if (modelData.healthStatus === "session_expired") return configRoot.safeI18n("Expirada");
                                            if (modelData.healthStatus === "not_configured") return configRoot.safeI18n("Não config.");
                                            return modelData.healthStatus;
                                        }
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize * 0.8
                                        font.bold: true
                                        color: "white"
                                    }
                                }
                            }

                            RowLayout {
                                spacing: Kirigami.Units.smallSpacing

                                QQC2.Label {
                                    text: "ID: " + modelData.id
                                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                                    color: Kirigami.Theme.disabledTextColor
                                }

                                QQC2.Label {
                                    text: "•"
                                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                                    color: Kirigami.Theme.disabledTextColor
                                }

                                QQC2.Label {
                                    text: modelData.source === "auto" ? configRoot.safeI18n("Detecção automática") : configRoot.safeI18n("Configuração manual")
                                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                                    color: Kirigami.Theme.disabledTextColor
                                }
                            }
                        }

                        // Botão de Renomear Conta
                        PlasmaComponents3.Button {
                            id: renameAccountBtn
                            icon.name: "document-edit"
                            text: configRoot.safeI18n("Renomear conta")
                            display: QQC2.AbstractButton.IconOnly
                            enabled: !configRoot.isBusy

                            QQC2.ToolTip.visible: hovered
                            QQC2.ToolTip.text: configRoot.safeI18n("Renomear conta '%1'", modelData.name || modelData.id)

                            onClicked: {
                                configRoot.requestRenameAccount(modelData);
                            }
                        }

                        // Botão de Excluir / Remover Conta
                        PlasmaComponents3.Button {
                            id: deleteAccountBtn
                            icon.name: "delete"
                            text: configRoot.safeI18n("Remover conta")
                            display: QQC2.AbstractButton.IconOnly
                            enabled: !configRoot.isBusy

                            QQC2.ToolTip.visible: hovered
                            QQC2.ToolTip.text: configRoot.safeI18n("Remover conta '%1'", modelData.name || modelData.id)

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
                    text: configRoot.safeI18n("Nenhuma conta cadastrada")
                    explanation: configRoot.safeI18n("Execute 'ai-usage-collector --refresh' para detectar credenciais locais ou cadastre contas em ~/.config/plasma-ai-usage/config.json")
                }
            }
        }

        // Perfis Órfãos: perfis em disco sem Conta cadastrada (nunca apagados sem confirmação)
        ColumnLayout {
            Layout.fillWidth: true
            visible: configRoot.orphanProfiles.length > 0
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                level: 4
                text: configRoot.safeI18n("Perfis Órfãos")
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
                        text: configRoot.safeI18n("Reimportar")
                        enabled: !configRoot.isBusy
                        onClicked: configRoot.runOrphanAction("--reimport-orphan", modelData, false)
                    }

                    PlasmaComponents3.Button {
                        text: configRoot.safeI18n("Excluir")
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

    // Diálogo de confirmação de exclusão de Perfil Órfão
    QQC2.Dialog {
        id: orphanDeleteDialog
        title: configRoot.safeI18n("Excluir Perfil Órfão")
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                text: configRoot.orphanPendingDeletion
                    ? configRoot.safeI18n("Excluir definitivamente o perfil '%1' do disco? As credenciais dele serão apagadas.", configRoot.orphanPendingDeletion.id)
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
                    text: configRoot.safeI18n("Cancelar")
                    onClicked: orphanDeleteDialog.close()
                }

                PlasmaComponents3.Button {
                    text: configRoot.safeI18n("Excluir Perfil")
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
        title: configRoot.safeI18n("Confirmar Remoção de Conta")
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                text: {
                    var acc = configRoot.accountPendingDeletion;
                    if (!acc) return "";
                    return configRoot.safeI18n(
                        "Deseja realmente remover a conta '%1' (ID: %2) do provedor %3?\n\nEsta operação removerá a conta do arquivo de configuração e atualizará o widget imediatamente.",
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
                    text: configRoot.safeI18n("Cancelar")
                    onClicked: confirmDialog.close()
                }

                PlasmaComponents3.Button {
                    id: confirmDeleteButton
                    text: configRoot.safeI18n("Remover Conta")
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
        title: configRoot.safeI18n("Renomear Conta")
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                text: {
                    var acc = configRoot.accountPendingRename;
                    if (!acc) return "";
                    return configRoot.safeI18n(
                        "Digite o novo nome para a conta '%1' (ID: %2) do provedor %3:",
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
                placeholderText: configRoot.safeI18n("Novo nome da conta")
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
                    text: configRoot.safeI18n("Cancelar")
                    onClicked: renameDialog.close()
                }

                PlasmaComponents3.Button {
                    id: saveRenameButton
                    text: configRoot.safeI18n("Salvar")
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
