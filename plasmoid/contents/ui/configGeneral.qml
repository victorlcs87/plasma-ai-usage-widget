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

    implicitWidth: Kirigami.Units.gridUnit * 30
    implicitHeight: Kirigami.Units.gridUnit * 25

    property var statusData: null
    property bool isLoading: false
    property bool isDeleting: false
    property string statusMessage: ""
    property string errorMessage: ""
    property var accountPendingDeletion: null

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
                configRoot.errorMessage = configRoot.safeI18n("Falha ao remover conta: %1", stderr || stdout || safeI18n("Erro desconhecido"));
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
                enabled: !configRoot.isLoading && !configRoot.isDeleting
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
            text: configRoot.safeI18n("Visualize as contas cadastradas de Claude, Codex e Gemini e exclua contas obsoletas diretamente.")
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }

        // Barra de progresso durante carregamento ou exclusão
        QQC2.ProgressBar {
            id: configProgressBar
            Layout.fillWidth: true
            Layout.preferredHeight: 4
            indeterminate: true
            visible: configRoot.isLoading || configRoot.isDeleting
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

                        // Botão de Excluir / Remover Conta
                        PlasmaComponents3.Button {
                            id: deleteAccountBtn
                            icon.name: "delete"
                            text: configRoot.safeI18n("Remover conta")
                            display: QQC2.AbstractButton.IconOnly
                            enabled: !configRoot.isDeleting

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
        standardButtons: QQC2.Dialog.Cancel

        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

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
                Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.Button {
                    text: configRoot.safeI18n("Cancelar")
                    onClicked: confirmDialog.close()
                }

                PlasmaComponents3.Button {
                    id: confirmDeleteButton
                    text: configRoot.safeI18n("Remover Conta")
                    icon.name: "delete"
                    highlighted: true
                    onClicked: {
                        confirmDialog.close();
                        configRoot.confirmDelete();
                    }
                }
            }
        }
    }
}
