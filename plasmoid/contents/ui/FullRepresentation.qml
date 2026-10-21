import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: fullRoot

    property var plasmoidItem: null

    collapseMarginsHint: true

    // Mouse sobre o popup: não fecha por hover enquanto estiver nele
    HoverHandler {
        onHoveredChanged: if (fullRoot.plasmoidItem) fullRoot.plasmoidItem.setPopupHovered(hovered)
    }
    Keys.onEscapePressed: if (fullRoot.plasmoidItem) fullRoot.plasmoidItem.closePopup()

    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.preferredWidth: Kirigami.Units.gridUnit * 25
    Layout.maximumWidth: Kirigami.Units.gridUnit * 35
    Layout.minimumHeight: Kirigami.Units.gridUnit * 22
    Layout.preferredHeight: Kirigami.Units.gridUnit * 28

    function safeI18n(text, arg1, arg2) {
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

    function getAccountsCount(providerKey) {
        if (!fullRoot.plasmoidItem || !fullRoot.plasmoidItem.statusData || !fullRoot.plasmoidItem.statusData.agents) {
            return 0;
        }
        var agents = fullRoot.plasmoidItem.statusData.agents;
        if (!providerKey) {
            var total = 0;
            for (var k in agents) {
                if (agents.hasOwnProperty(k) && agents[k].accounts) {
                    total += agents[k].accounts.length;
                }
            }
            return total;
        }
        return (agents[providerKey] && agents[providerKey].accounts) ? agents[providerKey].accounts.length : 0;
    }

    function getFilteredAccounts() {
        if (!fullRoot.plasmoidItem || !fullRoot.plasmoidItem.statusData || !fullRoot.plasmoidItem.statusData.agents) {
            return [];
        }
        var agents = fullRoot.plasmoidItem.statusData.agents;
        var list = [];
        var targetProvider = "";
        if (tabBar.currentIndex === 1) targetProvider = "claude";
        else if (tabBar.currentIndex === 2) targetProvider = "codex";
        else if (tabBar.currentIndex === 3) targetProvider = "gemini";

        for (var key in agents) {
            if (!agents.hasOwnProperty(key)) continue;
            if (targetProvider && key.toLowerCase() !== targetProvider) continue;
            var ag = agents[key];
            if (ag && ag.accounts && Array.isArray(ag.accounts)) {
                for (var i = 0; i < ag.accounts.length; i++) {
                    var acc = ag.accounts[i];
                    if (!acc.provider) {
                        acc.provider = key;
                    }
                    list.push(acc);
                }
            }
        }
        return list;
    }

    header: PlasmaExtras.PlasmoidHeading {
        RowLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: fullRoot.plasmoidItem?.Plasmoid?.icon || (typeof Plasmoid !== "undefined" ? Plasmoid.icon : "view-split-left-right")
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: Kirigami.Units.iconSizes.smallMedium
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Kirigami.Heading {
                    level: 3
                    text: fullRoot.safeI18n("Monitor de Uso de IA")
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                QQC2.Label {
                    text: fullRoot.plasmoidItem?.lastUpdatedFormatted || fullRoot.safeI18n("Atualização recente")
                    font.pointSize: Kirigami.Theme.smallFont.pointSize * 0.85
                    color: Kirigami.Theme.disabledTextColor
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            PlasmaComponents3.Button {
                id: refreshButton
                icon.name: "view-refresh"
                text: fullRoot.safeI18n("Atualizar agora")
                display: QQC2.AbstractButton.IconOnly
                enabled: !Boolean(fullRoot.plasmoidItem && fullRoot.plasmoidItem.isRefreshing)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.text: (fullRoot.plasmoidItem && fullRoot.plasmoidItem.isRefreshing)
                    ? fullRoot.safeI18n("Atualizando métricas...")
                    : fullRoot.safeI18n("Atualizar agora")

                onClicked: {
                    if (fullRoot.plasmoidItem) {
                        fullRoot.plasmoidItem.refreshCollector();
                    }
                }

                RotationAnimator on rotation {
                    from: 0
                    to: 360
                    duration: 1000
                    loops: Animation.Infinite
                    running: Boolean(fullRoot.plasmoidItem && fullRoot.plasmoidItem.isRefreshing)
                }
            }

            PlasmaComponents3.Button {
                id: configureButton
                icon.name: "configure"
                text: fullRoot.safeI18n("Configurações")
                display: QQC2.AbstractButton.IconOnly
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.text: fullRoot.safeI18n("Gerenciar contas e configurações")
                visible: (typeof Plasmoid !== "undefined" && Plasmoid && typeof Plasmoid.internalAction === "function" && Boolean(Plasmoid.internalAction("configure")))
                onClicked: {
                    if (typeof Plasmoid !== "undefined" && Plasmoid.internalAction) {
                        var act = Plasmoid.internalAction("configure");
                        if (act) act.trigger();
                    }
                }
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        // Barra de progresso visual indeterminada durante atualização assíncrona
        QQC2.ProgressBar {
            id: refreshProgressBar
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            indeterminate: true
            visible: Boolean(fullRoot.plasmoidItem && (fullRoot.plasmoidItem.isRefreshing || fullRoot.plasmoidItem.isLoading))
        }

        // Abas para alternar provedores (Claude, Codex, Gemini) ou visão consolidada ("Todos")
        PlasmaComponents3.TabBar {
            id: tabBar
            Layout.fillWidth: true
            currentIndex: 0

            PlasmaComponents3.TabButton {
                text: {
                    var count = fullRoot.getAccountsCount("");
                    return count > 0 ? fullRoot.safeI18n("Todos (%1)", count) : fullRoot.safeI18n("Todos");
                }
            }

            PlasmaComponents3.TabButton {
                text: {
                    var count = fullRoot.getAccountsCount("claude");
                    return count > 0 ? fullRoot.safeI18n("Claude (%1)", count) : "Claude";
                }
            }

            PlasmaComponents3.TabButton {
                text: {
                    var count = fullRoot.getAccountsCount("codex");
                    return count > 0 ? fullRoot.safeI18n("Codex (%1)", count) : "Codex";
                }
            }

            PlasmaComponents3.TabButton {
                text: {
                    var count = fullRoot.getAccountsCount("gemini");
                    return count > 0 ? fullRoot.safeI18n("Gemini (%1)", count) : "Gemini";
                }
            }
        }

        // Mensagem de erro caso o status.json não tenha sido lido
        Rectangle {
            visible: Boolean(fullRoot.plasmoidItem && fullRoot.plasmoidItem.lastError)
            Layout.fillWidth: true
            implicitHeight: errorLabel.implicitHeight + Kirigami.Units.smallSpacing * 2
            radius: 4
            color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, "#e74c3c", 0.2)
            border.color: "#e74c3c"
            border.width: 1

            QQC2.Label {
                id: errorLabel
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                text: fullRoot.plasmoidItem ? (fullRoot.plasmoidItem.lastError || "") : ""
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.Wrap
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }

        // Lista de Cards de Contas
        PlasmaComponents3.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true

            QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

            contentItem: ListView {
                id: accountsListView
                spacing: Kirigami.Units.smallSpacing
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                model: fullRoot.getFilteredAccounts()

                delegate: AccountCard {
                    width: accountsListView.width
                    accountData: modelData
                    plasmoidItem: fullRoot.plasmoidItem
                    onAccountSwitched: {
                        if (fullRoot.plasmoidItem && typeof fullRoot.plasmoidItem.loadStatus === "function") {
                            fullRoot.plasmoidItem.loadStatus();
                        }
                    }
                }

                // Placeholder quando não houver contas
                PlasmaExtras.PlaceholderMessage {
                    anchors.centerIn: parent
                    width: parent.width - Kirigami.Units.gridUnit * 2
                    visible: accountsListView.count === 0
                    iconName: "preferences-system-network"
                    text: fullRoot.safeI18n("Nenhuma conta encontrada")
                    explanation: fullRoot.safeI18n("Execute 'ai-usage-collector --refresh' para detectar credenciais locais ou cadastre contas em ~/.config/plasma-ai-usage/config.json")
                }
            }
        }
    }
}
