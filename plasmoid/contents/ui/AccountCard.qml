import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as Plasma5Support

Kirigami.AbstractCard {
    id: cardRoot

    property var accountData: ({})
    property var plasmoidItem: null
    property int liveSecondsRemaining: 0
    property int liveWeeklySecondsRemaining: 0
    property bool copiedFeedback: false
    property bool isSwitching: false
    property string switchError: ""

    readonly property bool isActive: Boolean(cardRoot.accountData && (cardRoot.accountData.isActive === true || cardRoot.accountData.is_active === true))

    signal accountSwitched()

    Plasma5Support.DataSource {
        id: switchDataSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            cardRoot.isSwitching = false;
            var exitCode = data["exit code"];
            var stdout = (data["stdout"] || "").trim();
            var stderr = (data["stderr"] || "").trim();

            if (exitCode === 0) {
                cardRoot.switchError = "";
                var jsonStart = stdout.indexOf("{");
                if (jsonStart !== -1) {
                    try {
                        var parsed = JSON.parse(stdout.substring(jsonStart));
                        if (cardRoot.plasmoidItem) {
                            cardRoot.plasmoidItem.statusData = parsed;
                        }
                    } catch (e) {
                        // ignore parse error and rely on loadStatus
                    }
                }
                if (cardRoot.plasmoidItem && typeof cardRoot.plasmoidItem.loadStatus === "function") {
                    cardRoot.plasmoidItem.loadStatus();
                }
                cardRoot.accountSwitched();
            } else {
                var errMsg = stderr || stdout || cardRoot.safeI18n("Código de saída %1", exitCode);
                cardRoot.switchError = cardRoot.safeI18n("Erro ao alternar conta: %1", errMsg);
                if (cardRoot.plasmoidItem) {
                    cardRoot.plasmoidItem.lastError = cardRoot.switchError;
                }
            }
            disconnectSource(sourceName);
        }
    }

    Timer {
        id: copiedFeedbackTimer
        interval: 2500
        running: false
        repeat: false
        onTriggered: cardRoot.copiedFeedback = false
    }

    Plasma5Support.DataSource {
        id: clipboardDataSource
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            disconnectSource(sourceName);
        }
    }

    TextInput {
        id: clipHelper
        visible: false
    }

    function shellQuote(str) {
        if (str === null || str === undefined) return "''";
        return "'" + String(str).replace(/'/g, "'\\''") + "'";
    }

    function copyToClipboard(text) {
        if (!text) return;
        // 1. Cópia local Qt/QML
        clipHelper.text = text;
        clipHelper.selectAll();
        clipHelper.copy();

        // 2. Cópia segura para o clipboard do sistema (Wayland wl-copy ou X11 xclip)
        // Passa o texto seguro entre aspas simples POSIX como argumento posicional $1 para bash
        var safeText = shellQuote(text);
        var cmd = "bash -c 'if command -v wl-copy >/dev/null 2>&1; then printf \"%s\" \"$1\" | wl-copy; " +
                  "elif command -v xclip >/dev/null 2>&1; then printf \"%s\" \"$1\" | xclip -selection clipboard; fi' _ " +
                  safeText;
        clipboardDataSource.connectSource(cmd);

        // 3. Feedback visual imediato
        cardRoot.copiedFeedback = true;
        copiedFeedbackTimer.restart();
    }

    function buildCollectorCommand(quotedArgs) {
        return "bash -c 'if command -v ai-usage-collector >/dev/null 2>&1; then ai-usage-collector \"$@\"; " +
               "elif [ -x \"$HOME/.local/bin/ai-usage-collector\" ]; then \"$HOME/.local/bin/ai-usage-collector\" \"$@\"; " +
               "elif [ -x \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" ]; then \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" \"$@\"; " +
               "else python3 -m ai_usage_collector \"$@\"; fi' _ " + (quotedArgs || "");
    }

    function switchAccount() {
        if (cardRoot.isSwitching) return;
        var prov = cardRoot.accountData?.provider;
        var accId = cardRoot.accountData?.id;
        if (!prov || !accId) return;

        var provClean = String(prov).toLowerCase().trim();
        if (["claude", "codex", "gemini"].indexOf(provClean) === -1) return;

        cardRoot.isSwitching = true;
        cardRoot.switchError = "";

        var safeArgs = shellQuote("--switch-account") + " " +
                       shellQuote(provClean) + " " +
                       shellQuote(accId) + " " +
                       shellQuote("--status");

        var cmd = cardRoot.buildCollectorCommand(safeArgs);
        switchDataSource.connectSource(cmd);
    }

    function safeI18n(text, arg1, arg2, arg3) {
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

    // Compute live countdowns for both active window and weekly cycle
    function updateCountdown() {
        if (!accountData) {
            liveSecondsRemaining = 0;
            liveWeeklySecondsRemaining = 0;
            return;
        }

        // 1. Janela Ativa/Horária
        var nw = accountData.native_window;
        if (nw) {
            var releaseIso = nw.release_time || nw.resets_at;
            if (releaseIso) {
                var targetMs = new Date(releaseIso).getTime();
                if (!isNaN(targetMs)) {
                    var diffSec = Math.floor((targetMs - Date.now()) / 1000);
                    liveSecondsRemaining = Math.max(0, diffSec);
                } else {
                    liveSecondsRemaining = (nw.seconds_remaining !== undefined && nw.seconds_remaining !== null)
                        ? Math.max(0, nw.seconds_remaining)
                        : 0;
                }
            } else if (nw.seconds_remaining !== undefined && nw.seconds_remaining !== null) {
                liveSecondsRemaining = Math.max(0, nw.seconds_remaining);
            } else {
                liveSecondsRemaining = 0;
            }
        } else {
            liveSecondsRemaining = 0;
        }

        // 2. Janela Semanal (7 dias)
        var ww = accountData.weekly_window;
        if (ww) {
            var weeklyResetIso = ww.resets_at || ww.cycle_reset_time;
            if (weeklyResetIso) {
                var weeklyTargetMs = new Date(weeklyResetIso).getTime();
                if (!isNaN(weeklyTargetMs)) {
                    var weeklyDiffSec = Math.floor((weeklyTargetMs - Date.now()) / 1000);
                    liveWeeklySecondsRemaining = Math.max(0, weeklyDiffSec);
                } else {
                    liveWeeklySecondsRemaining = (ww.seconds_remaining !== undefined && ww.seconds_remaining !== null)
                        ? Math.max(0, ww.seconds_remaining)
                        : 0;
                }
            } else if (ww.seconds_remaining !== undefined && ww.seconds_remaining !== null) {
                liveWeeklySecondsRemaining = Math.max(0, ww.seconds_remaining);
            } else {
                liveWeeklySecondsRemaining = 0;
            }
        } else {
            liveWeeklySecondsRemaining = 0;
        }
    }

    Timer {
        id: countdownTimer
        interval: 1000
        running: true
        repeat: true
        onTriggered: cardRoot.updateCountdown()
    }

    onAccountDataChanged: {
        updateCountdown();
    }

    Component.onCompleted: {
        updateCountdown();
    }

    function formatCountdown(sec) {
        if (sec <= 0) {
            return safeI18n("Liberada");
        }
        var hours = Math.floor(sec / 3600);
        var minutes = Math.floor((sec % 3600) / 60);
        var seconds = Math.floor(sec % 60);

        if (hours >= 24) {
            var days = Math.floor(hours / 24);
            var remH = hours % 24;
            return safeI18n("%1d %2h restantes", days, remH);
        } else if (hours > 0) {
            var mStr = (minutes < 10 ? "0" : "") + minutes;
            return safeI18n("%1h %2m restantes", hours, mStr);
        } else if (minutes > 0) {
            var sStr = (seconds < 10 ? "0" : "") + seconds;
            return safeI18n("%1m %2s restantes", minutes, sStr);
        } else {
            return safeI18n("%1s restantes", seconds);
        }
    }

    function formatTime(isoStr) {
        if (!isoStr) return "";
        try {
            var d = new Date(isoStr);
            if (isNaN(d.getTime())) return "";
            var h = d.getHours();
            var m = d.getMinutes();
            return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
        } catch (e) {
            return "";
        }
    }

    function formatDateTime(isoStr) {
        if (!isoStr) return "";
        try {
            var d = new Date(isoStr);
            if (isNaN(d.getTime())) return "";
            var day = ("0" + d.getDate()).slice(-2);
            var month = ("0" + (d.getMonth() + 1)).slice(-2);
            var h = ("0" + d.getHours()).slice(-2);
            var m = ("0" + d.getMinutes()).slice(-2);
            return day + "/" + month + " " + h + ":" + m;
        } catch (e) {
            return "";
        }
    }

    function formatNumber(num) {
        if (num === null || num === undefined) return "0";
        return num.toLocaleString();
    }

    function formatPercentage(percentage) {
        if (percentage === null || percentage === undefined || isNaN(percentage)) return "0%";
        return Math.round(Number(percentage)) + "%";
    }

    function getUsageColor(percentage) {
        var val = (percentage === null || percentage === undefined || isNaN(percentage)) ? 0 : Number(percentage);
        if (val < 70) {
            return Kirigami.Theme.positiveTextColor;
        } else if (val <= 90) {
            return Kirigami.Theme.neutralTextColor;
        } else {
            return Kirigami.Theme.negativeTextColor;
        }
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

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        // Linha 1: Provedor, Nome da Conta e Status de Saúde
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Rectangle {
                implicitWidth: providerLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                implicitHeight: providerLabel.implicitHeight + Kirigami.Units.smallSpacing
                radius: 4
                color: cardRoot.getProviderColor(cardRoot.accountData?.provider)

                QQC2.Label {
                    id: providerLabel
                    anchors.centerIn: parent
                    text: (cardRoot.accountData?.provider || "IA").toUpperCase()
                    font.bold: true
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: "white"
                }
            }

            QQC2.Label {
                Layout.fillWidth: true
                text: cardRoot.accountData?.name || cardRoot.accountData?.label || cardRoot.safeI18n("Conta")
                font.bold: true
                elide: Text.ElideRight
                color: Kirigami.Theme.textColor
            }

            // Botão de Ativação Rápida no Sistema (apenas para contas inativas com saúde válida)
            PlasmaComponents3.Button {
                id: switchAccountButton
                visible: !cardRoot.isActive && (cardRoot.accountData?.health?.status === "valid")
                enabled: !cardRoot.isSwitching
                text: cardRoot.isSwitching ? cardRoot.safeI18n("Ativando...") : cardRoot.safeI18n("⚡ Ativar no Sistema")
                icon.name: cardRoot.isSwitching ? "view-refresh" : "system-run"
                font.pointSize: Kirigami.Theme.smallFont.pointSize

                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.text: {
                    if (cardRoot.isSwitching) return cardRoot.safeI18n("Ativando conta no sistema...");
                    if (cardRoot.switchError && cardRoot.switchError.length > 0) return cardRoot.switchError;
                    return cardRoot.safeI18n("Ativar esta conta como perfil padrão no CLI do sistema");
                }

                onClicked: {
                    cardRoot.switchAccount();
                }
            }

            // Badge de Conta Ativa no CLI
            Rectangle {
                id: activeCliBadge
                visible: cardRoot.isActive
                implicitWidth: activeCliLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                implicitHeight: activeCliLabel.implicitHeight + Kirigami.Units.smallSpacing
                radius: 4
                color: Kirigami.Theme.highlightColor

                QQC2.Label {
                    id: activeCliLabel
                    anchors.centerIn: parent
                    text: cardRoot.safeI18n("✓ Ativa no CLI")
                    font.bold: true
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: Kirigami.Theme.highlightedTextColor || "white"
                }

                QQC2.ToolTip.text: cardRoot.safeI18n("Esta conta está configurada como a conta ativa no sistema.")
                QQC2.ToolTip.visible: activeCliMouseArea.containsMouse

                MouseArea {
                    id: activeCliMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                }
            }

            Rectangle {
                id: healthBadge
                implicitWidth: healthText.implicitWidth + Kirigami.Units.smallSpacing * 2
                implicitHeight: healthText.implicitHeight + Kirigami.Units.smallSpacing
                radius: 4

                property string healthStatus: cardRoot.accountData?.health?.status || "unknown"

                color: {
                    if (healthStatus === "valid") return "#27ae60";
                    if (healthStatus === "session_expired") return "#f39c12";
                    if (healthStatus === "not_configured") return "#7f8c8d";
                    return "#e74c3c";
                }

                QQC2.Label {
                    id: healthText
                    anchors.centerIn: parent
                    text: {
                        var st = healthBadge.healthStatus;
                        if (st === "valid") return cardRoot.safeI18n("Ativa");
                        if (st === "session_expired") return cardRoot.safeI18n("Expirada");
                        if (st === "not_configured") return cardRoot.safeI18n("Não config.");
                        return cardRoot.safeI18n("Erro");
                    }
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    font.bold: true
                    color: "white"
                }

                QQC2.ToolTip.text: cardRoot.accountData?.health?.message || ""
                QQC2.ToolTip.visible: healthMouseArea.containsMouse

                MouseArea {
                    id: healthMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                }
            }
        }

        // ==========================================
        // Medidor 1: Janela Ativa/Horária
        // ==========================================
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Math.round(Kirigami.Units.smallSpacing / 2)

            // Cabeçalho: Título da Janela e Porcentagem em Destaque
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    id: activeWindowTitleLabel
                    text: {
                        var winType = cardRoot.accountData?.native_window?.type || "";
                        if (winType === "5h") return cardRoot.safeI18n("Janela Ativa (5h)");
                        if (winType === "3h") return cardRoot.safeI18n("Janela Ativa (3h)");
                        if (winType === "daily") return cardRoot.safeI18n("Janela Diária");
                        if (winType) return cardRoot.safeI18n("Janela Ativa (%1)", winType);
                        return cardRoot.safeI18n("Janela Ativa");
                    }
                    font.weight: Font.DemiBold
                    color: Kirigami.Theme.textColor
                }

                Item { Layout.fillWidth: true }

                QQC2.Label {
                    id: activeWindowPercentageLabel
                    property double pct: cardRoot.accountData?.native_window?.usage_percentage || 0.0
                    text: cardRoot.formatPercentage(pct)
                    font.bold: true
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize
                    color: cardRoot.getUsageColor(pct)

                    QQC2.ToolTip.visible: activePctMouseArea.containsMouse
                    QQC2.ToolTip.text: cardRoot.safeI18n("%1% consumido da cota horária/ativa", pct.toFixed(1))

                    MouseArea {
                        id: activePctMouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                    }
                }
            }

            // Barra de Progresso Proporcional da Janela Ativa
            QQC2.ProgressBar {
                id: nativeProgressBar
                Layout.fillWidth: true
                Layout.preferredHeight: 6
                from: 0.0
                to: 1.0
                value: (cardRoot.accountData?.native_window ? cardRoot.accountData.native_window.usage_percentage : 0.0) / 100.0

                background: Rectangle {
                    implicitHeight: 6
                    radius: 3
                    color: Kirigami.Theme.alternateBackgroundColor
                    border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)
                    border.width: 1
                }

                contentItem: Item {
                    implicitHeight: 6
                    Rectangle {
                        width: Math.min(parent.width, Math.max(0, nativeProgressBar.visualPosition * parent.width))
                        height: parent.height
                        radius: 3
                        color: cardRoot.getUsageColor(cardRoot.accountData?.native_window?.usage_percentage || 0.0)
                    }
                }
            }

            // Detalhes Complementares: Tokens Consumidos e Contagem Regressiva de Liberação
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "appointment-soon"
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                    color: cardRoot.liveSecondsRemaining > 0 ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.positiveTextColor
                }

                QQC2.Label {
                    id: activeWindowDetailsLabel
                    Layout.fillWidth: true
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: Kirigami.Theme.disabledTextColor
                    elide: Text.ElideRight
                    text: {
                        var nw = cardRoot.accountData?.native_window;
                        var parts = [];
                        if (nw && nw.tokens_used !== null && nw.tokens_used !== undefined && nw.tokens_used > 0) {
                            parts.push(cardRoot.safeI18n("%1 tokens", cardRoot.formatNumber(nw.tokens_used)));
                        }
                        var countdownStr = cardRoot.formatCountdown(cardRoot.liveSecondsRemaining);
                        var releaseIso = nw ? (nw.release_time || nw.resets_at) : null;
                        var timeStr = cardRoot.formatTime(releaseIso);
                        if (cardRoot.liveSecondsRemaining > 0 && timeStr.length > 0) {
                            parts.push(cardRoot.safeI18n("Liberação: %1 (%2)", countdownStr, timeStr));
                        } else if (cardRoot.liveSecondsRemaining > 0) {
                            parts.push(cardRoot.safeI18n("Liberação: %1", countdownStr));
                        } else {
                            parts.push(cardRoot.safeI18n("Cota liberada"));
                        }
                        return parts.join(" • ");
                    }
                }
            }
        }

        // ==========================================
        // Medidor 2: Janela Semanal (7 dias)
        // ==========================================
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Math.round(Kirigami.Units.smallSpacing / 2)

            // Cabeçalho: Título da Janela Semanal e Porcentagem em Destaque
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    id: weeklyWindowTitleLabel
                    text: cardRoot.safeI18n("Janela Semanal (7 dias)")
                    font.weight: Font.DemiBold
                    color: Kirigami.Theme.textColor
                }

                Item { Layout.fillWidth: true }

                QQC2.Label {
                    id: weeklyWindowPercentageLabel
                    property double weeklyPct: (cardRoot.accountData?.weekly_window?.usage_percentage !== undefined && cardRoot.accountData?.weekly_window?.usage_percentage !== null)
                        ? cardRoot.accountData.weekly_window.usage_percentage
                        : 0.0
                    text: cardRoot.formatPercentage(weeklyPct)
                    font.bold: true
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize
                    color: cardRoot.getUsageColor(weeklyPct)

                    QQC2.ToolTip.visible: weeklyPctMouseArea.containsMouse
                    QQC2.ToolTip.text: cardRoot.safeI18n("%1% consumido da cota semanal", weeklyPct.toFixed(1))

                    MouseArea {
                        id: weeklyPctMouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                    }
                }
            }

            // Barra de Progresso Proporcional da Janela Semanal
            QQC2.ProgressBar {
                id: weeklyProgressBar
                Layout.fillWidth: true
                Layout.preferredHeight: 6
                from: 0.0
                to: 1.0
                value: (cardRoot.accountData?.weekly_window ? cardRoot.accountData.weekly_window.usage_percentage : 0) / 100.0

                background: Rectangle {
                    implicitHeight: 6
                    radius: 3
                    color: Kirigami.Theme.alternateBackgroundColor
                    border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)
                    border.width: 1
                }

                contentItem: Item {
                    implicitHeight: 6
                    Rectangle {
                        width: Math.min(parent.width, Math.max(0, weeklyProgressBar.visualPosition * parent.width))
                        height: parent.height
                        radius: 3
                        color: cardRoot.getUsageColor(cardRoot.accountData?.weekly_window ? cardRoot.accountData.weekly_window.usage_percentage : 0)
                    }
                }
            }

            // Detalhes Complementares: Tokens Acumulados na Semana e Data/Hora de Virada do Ciclo
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "view-calendar-timeline"
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                    color: Kirigami.Theme.disabledTextColor
                }

                QQC2.Label {
                    id: weeklyWindowDetailsLabel
                    Layout.fillWidth: true
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: Kirigami.Theme.disabledTextColor
                    elide: Text.ElideRight
                    text: {
                        var ww = cardRoot.accountData?.weekly_window;
                        if (!ww) return cardRoot.safeI18n("Ciclo semanal regular");
                        var parts = [];
                        if (ww.tokens_used !== null && ww.tokens_used !== undefined && ww.tokens_used > 0) {
                            parts.push(cardRoot.safeI18n("%1 tokens", cardRoot.formatNumber(ww.tokens_used)));
                        }
                        var resetIso = ww.resets_at || ww.cycle_reset_time;
                        var dateStr = cardRoot.formatDateTime(resetIso);
                        var countdownStr = cardRoot.formatCountdown(cardRoot.liveWeeklySecondsRemaining);
                        if (cardRoot.liveWeeklySecondsRemaining > 0 && dateStr.length > 0) {
                            parts.push(cardRoot.safeI18n("Virada: %1 (%2)", dateStr, countdownStr));
                        } else if (dateStr.length > 0) {
                            parts.push(cardRoot.safeI18n("Virada: %1", dateStr));
                        } else if (cardRoot.liveWeeklySecondsRemaining > 0) {
                            parts.push(cardRoot.safeI18n("Virada: %1", countdownStr));
                        } else {
                            parts.push(cardRoot.safeI18n("Ciclo regular"));
                        }
                        return parts.join(" • ");
                    }
                }
            }
        }

        UsageDetails {
            Layout.fillWidth: true
            details: cardRoot.accountData?.usage_details ?? null
        }

        // ==========================================
        // Medidor 3: Badge de Convites de Teste Gratuito
        // ==========================================
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            visible: {
                var invites = cardRoot.accountData?.free_trial_invites;
                return Boolean(invites && invites.available_count > 0);
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: inviteRow.implicitHeight + Kirigami.Units.smallSpacing * 2
                radius: 4
                color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.highlightColor, "#f1c40f", 0.25)
                border.color: "#f39c12"
                border.width: 1

                RowLayout {
                    id: inviteRow
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.smallSpacing
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: "mail-message-new"
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: Kirigami.Units.iconSizes.small
                        color: "#d35400"
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        font.bold: true
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        color: Kirigami.Theme.textColor
                        text: {
                            var count = cardRoot.accountData?.free_trial_invites?.available_count || 0;
                            return count === 1
                                ? cardRoot.safeI18n("1 convite de teste gratuito disponível")
                                : cardRoot.safeI18n("%1 convites de teste gratuito disponíveis", count);
                        }
                    }

                    QQC2.Button {
                        id: copyInviteButton
                        visible: Boolean(cardRoot.accountData?.free_trial_invites?.invite_url)
                        text: cardRoot.copiedFeedback ? cardRoot.safeI18n("Copiado!") : cardRoot.safeI18n("Copiar Link")
                        icon.name: cardRoot.copiedFeedback ? "emblem-ok-symbolic" : "edit-copy"
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        highlighted: cardRoot.copiedFeedback

                        QQC2.ToolTip.visible: hovered || cardRoot.copiedFeedback
                        QQC2.ToolTip.text: cardRoot.copiedFeedback
                            ? cardRoot.safeI18n("Link copiado para a Área de Transferência!")
                            : cardRoot.safeI18n("Copiar link de convite para a Área de Transferência")

                        onClicked: {
                            var url = cardRoot.accountData?.free_trial_invites?.invite_url;
                            if (url) {
                                cardRoot.copyToClipboard(url);
                            }
                        }
                    }

                    QQC2.Label {
                        visible: cardRoot.copiedFeedback
                        text: cardRoot.safeI18n("Copiado!")
                        font.bold: true
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        color: Kirigami.Theme.positiveTextColor
                    }
                }
            }
        }
    }
}
