import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as Plasma5Support

Kirigami.AbstractCard {
    id: cardRoot

    property var accountData: ({})
    property int liveSecondsRemaining: 0
    property bool copiedFeedback: false

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

    function copyToClipboard(text) {
        if (!text) return;
        // 1. Cópia local Qt/QML
        clipHelper.text = text;
        clipHelper.selectAll();
        clipHelper.copy();

        // 2. Cópia para o clipboard do sistema (Wayland wl-copy ou X11 xclip)
        var escaped = text.replace(/'/g, "'\\''");
        var cmd = "bash -c 'if command -v wl-copy >/dev/null 2>&1; then printf \"%s\" \"" + escaped + "\" | wl-copy; " +
                  "elif command -v xclip >/dev/null 2>&1; then printf \"%s\" \"" + escaped + "\" | xclip -selection clipboard; fi'";
        clipboardDataSource.connectSource(cmd);

        // 3. Feedback visual imediato
        cardRoot.copiedFeedback = true;
        copiedFeedbackTimer.restart();
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

    // Compute live countdown
    function updateCountdown() {
        if (!accountData || !accountData.native_window) {
            liveSecondsRemaining = 0;
            return;
        }

        var nw = accountData.native_window;
        if (nw.release_time) {
            var targetMs = new Date(nw.release_time).getTime();
            if (!isNaN(targetMs)) {
                var nowMs = Date.now();
                var diffSec = Math.floor((targetMs - nowMs) / 1000);
                liveSecondsRemaining = Math.max(0, diffSec);
                return;
            }
        }

        if (nw.seconds_remaining !== undefined && nw.seconds_remaining !== null) {
            liveSecondsRemaining = Math.max(0, nw.seconds_remaining);
        } else {
            liveSecondsRemaining = 0;
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
            return safeI18n("Cota totalmente liberada");
        }
        var hours = Math.floor(sec / 3600);
        var minutes = Math.floor((sec % 3600) / 60);
        var seconds = Math.floor(sec % 60);

        if (hours > 24) {
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

    function formatNumber(num) {
        if (num === null || num === undefined) return "0";
        return num.toLocaleString();
    }

    function getUsageColor(percentage) {
        if (percentage < 70) {
            return "#27ae60"; // Verde (< 70%)
        } else if (percentage <= 90) {
            return "#f39c12"; // Amarelo (70% a 90%)
        } else {
            return "#e74c3c"; // Vermelho (> 90%)
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

        // Linha 2: Janela Nativa - Título e Porcentagem
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: {
                    var winType = cardRoot.accountData?.native_window?.type || "";
                    if (winType === "5h") return cardRoot.safeI18n("Janela nativa (5h)");
                    if (winType === "3h") return cardRoot.safeI18n("Janela nativa (3h)");
                    if (winType === "daily") return cardRoot.safeI18n("Janela nativa (Diária)");
                    return cardRoot.safeI18n("Janela nativa (%1)", winType);
                }
                font.weight: Font.DemiBold
                color: Kirigami.Theme.textColor
            }

            Item { Layout.fillWidth: true }

            QQC2.Label {
                property double pct: cardRoot.accountData?.native_window?.usage_percentage || 0.0
                text: pct.toFixed(1) + "%"
                font.bold: true
                color: cardRoot.getUsageColor(pct)
            }
        }

        // Linha 3: Barra de Progresso com Dinamismo de Cores
        QQC2.ProgressBar {
            id: nativeProgressBar
            Layout.fillWidth: true
            Layout.preferredHeight: 8
            from: 0
            to: 100
            value: cardRoot.accountData?.native_window?.usage_percentage || 0.0

            background: Rectangle {
                implicitHeight: 8
                radius: 4
                color: Kirigami.Theme.alternateBackgroundColor
                border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)
                border.width: 1
            }

            contentItem: Item {
                implicitHeight: 8
                Rectangle {
                    width: nativeProgressBar.visualPosition * parent.width
                    height: parent.height
                    radius: 4
                    color: cardRoot.getUsageColor(nativeProgressBar.value)
                }
            }
        }

        // Linha 4: Capacidade Disponível e Utilizada
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Kirigami.Theme.disabledTextColor
                text: {
                    var nw = cardRoot.accountData?.native_window;
                    if (!nw) return "";
                    var used = nw.used_capacity !== null && nw.used_capacity !== undefined ? nw.used_capacity : 0;
                    var total = nw.total_capacity !== null && nw.total_capacity !== undefined ? nw.total_capacity : 0;
                    var avail = nw.available_capacity !== null && nw.available_capacity !== undefined ? nw.available_capacity : Math.max(0, total - used);
                    return cardRoot.safeI18n("Capacidade: %1 / %2 utilizado • %3 disponível", used, total, avail);
                }
            }
        }

        // Linha 5: Tempo de Liberação com Contagem Regressiva
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
                Layout.fillWidth: true
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Kirigami.Theme.textColor
                text: {
                    var countdownStr = cardRoot.formatCountdown(cardRoot.liveSecondsRemaining);
                    var releaseIso = cardRoot.accountData?.native_window?.release_time;
                    var timeStr = cardRoot.formatTime(releaseIso);
                    if (cardRoot.liveSecondsRemaining > 0 && timeStr.length > 0) {
                        return cardRoot.safeI18n("Liberação: %1 (%2)", countdownStr, timeStr);
                    }
                    return cardRoot.safeI18n("Liberação: %1", countdownStr);
                }
            }
        }

        // Linha 6: Métrica da Janela Semanal (7 dias)
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            visible: {
                var ww = cardRoot.accountData?.weekly_window;
                return Boolean(ww && (ww.used_capacity !== null && ww.used_capacity !== undefined || ww.tokens_used));
            }

            Kirigami.Icon {
                source: "view-calendar-timeline"
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                color: Kirigami.Theme.disabledTextColor
            }

            QQC2.Label {
                Layout.fillWidth: true
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Kirigami.Theme.disabledTextColor
                elide: Text.ElideRight
                text: {
                    var ww = cardRoot.accountData?.weekly_window;
                    if (!ww) return "";
                    var parts = [];
                    if (ww.used_capacity !== null && ww.used_capacity !== undefined) {
                        parts.push(cardRoot.safeI18n("Janela semanal (7d): %1 msgs", cardRoot.formatNumber(ww.used_capacity)));
                    }
                    if (ww.tokens_used) {
                        parts.push(cardRoot.safeI18n("%1 tokens", cardRoot.formatNumber(ww.tokens_used)));
                    }
                    if (ww.cycle_reset_time) {
                        var resetTimeStr = cardRoot.formatTime(ww.cycle_reset_time);
                        if (resetTimeStr) {
                            parts.push(cardRoot.safeI18n("renovação às %1", resetTimeStr));
                        }
                    }
                    return parts.join(" • ");
                }
            }
        }

        // Linha 7: Badge de Convites de Teste Gratuito
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
