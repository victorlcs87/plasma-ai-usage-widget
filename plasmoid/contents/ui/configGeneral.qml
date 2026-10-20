import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtCore

import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.plasma.extras as PlasmaExtras

Item {
    id: configRoot

    implicitWidth: Kirigami.Units.gridUnit * 32
    implicitHeight: Kirigami.Units.gridUnit * 28

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
                } catch (e) {
                    configRoot.errorMessage = configRoot.safeI18n("Erro ao ler dados de status: %1", e.message);
                }
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
