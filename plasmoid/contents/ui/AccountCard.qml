import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets
import "NotchModel.js" as NotchModel
import "ViewPrefs.js" as ViewPrefs
import "I18n.js" as I18n
import "Collector.js" as Collector

// Card de uma Conta no Notch escuro: Anel Duplo, nível, % (usado ou restante), liberação (contagem ou data),
// previsão, nota de limites, Estado da Sessão, detalhamentos, histórico e convites. Ações: ativar no sistema e
// copiar link de convite. Tudo derivado de `accountData` (contrato) e do relógio `nowMs` do popup.
Rectangle {
    id: cardRoot

    property var accountData: ({})
    property var plasmoidItem: null
    property double nowMs: Date.now()        // relógio do popup (1 s, só com o popup aberto)
    property var prefs: ViewPrefs.config({})  // preferências de exibição (ViewPrefs.config)
    property string sessionState: ""          // Estado da Sessão da Conta Ativa ("" = sem indicador)
    property color accent: Kirigami.Theme.highlightColor
    property bool animate: true               // false com o widget oculto (Passivo): nenhuma animação
    property bool reducedMotion: false
    property bool copiedFeedback: false
    property bool isSwitching: false
    property string switchError: ""
    property bool detailsOpen: false

    readonly property bool isActive: Boolean(cardRoot.accountData && (cardRoot.accountData.isActive === true || cardRoot.accountData.is_active === true))
    // ADR-0007: dados desatualizados (servidos do cache) ou ausentes (sem cache nem histórico local)
    readonly property bool isStale: cardRoot.accountData?.stale === true
    readonly property bool hasNoData: cardRoot.accountData?.no_data === true
    readonly property var nativeView: NotchModel.windowView(cardRoot.accountData || {}, cardRoot.accountData?.native_window, "native", cardRoot.prefs, cardRoot.nowMs, I18n.tr)
    readonly property var weeklyView: NotchModel.windowView(cardRoot.accountData || {}, cardRoot.accountData?.weekly_window, "weekly", cardRoot.prefs, cardRoot.nowMs, I18n.tr)
    readonly property bool hasDetails: Boolean(cardRoot.accountData?.token_history) || NotchModel.hasUsageDetails(cardRoot.accountData?.usage_details)
    readonly property string healthStatus: cardRoot.accountData?.health?.status || "unknown"
    readonly property string accountName: cardRoot.accountData?.name || cardRoot.accountData?.label || I18n.tr("Account")

    signal accountSwitched()

    implicitHeight: body.implicitHeight + Kirigami.Units.smallSpacing * 3
    radius: 8
    color: Presets.ui.card
    border.width: cardRoot.isActive ? 2 : 1
    border.color: cardRoot.isActive ? cardRoot.accent : Presets.ui.edge

    Accessible.role: Accessible.Grouping
    Accessible.name: I18n.tr("%1, account %2", Presets.providerInfo(cardRoot.accountData?.provider).name, cardRoot.accountName)
    Accessible.description: [
        cardRoot.isActive ? I18n.tr("Active on the system") : "",
        NotchModel.viewSummary(cardRoot.nativeView, cardRoot.prefs.remaining, I18n.tr),
        NotchModel.viewSummary(cardRoot.weeklyView, cardRoot.prefs.remaining, I18n.tr),
        NotchModel.sessionWord(cardRoot.sessionState, I18n.tr)
    ].filter(function (x) { return x; }).join(". ")

    Component.onCompleted: cardRoot.detailsOpen = cardRoot.isActive && cardRoot.hasDetails

    Timer {
        id: copiedFeedbackTimer
        interval: 2500
        running: false
        repeat: false
        onTriggered: cardRoot.copiedFeedback = false
    }

    // Executor e área de transferência são únicos, do popup (FullRepresentation): o card só pede
    property var runCollector: function (quotedArgs, onDone) {}
    property var copyText: function (text) {}

    function copyToClipboard(text) {
        if (!text) return;
        cardRoot.copyText(text);
        cardRoot.copiedFeedback = true;
        copiedFeedbackTimer.restart();
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

        var safeArgs = Collector.shellQuote("--switch-account") + " " +
                       Collector.shellQuote(provClean) + " " +
                       Collector.shellQuote(accId) + " " +
                       Collector.shellQuote("--status");

        cardRoot.runCollector(safeArgs, cardRoot.onSwitched);
    }

    function onSwitched(data) {
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
            var errMsg = stderr || stdout || I18n.tr("Exit code %1", exitCode);
            cardRoot.switchError = I18n.tr("Error switching account: %1", errMsg);
            if (cardRoot.plasmoidItem) {
                cardRoot.plasmoidItem.lastError = cardRoot.switchError;
            }
        }
    }

    function limitChangeText(changes) {
        var now = Date.now();
        changes = (changes || []).filter(function (c) {
            return c && c.window && c.kind && !(c.expires_at && Date.parse(c.expires_at) <= now);
        });
        if (changes.length === 0) return "";
        var texts = {
            native: {
                added: I18n.tr("New active window"),
                removed: I18n.tr("Active window removed"),
                duration: I18n.tr("Active window with a different duration"),
                early_reset: I18n.tr("Active window with an early reset")
            },
            weekly: {
                added: I18n.tr("New weekly window"),
                removed: I18n.tr("Weekly window removed"),
                duration: I18n.tr("Weekly window with a different duration"),
                early_reset: I18n.tr("Weekly window with an early reset")
            }
        };
        return I18n.tr("Limits changed: %1", NotchModel.joined(changes.map(function (c) {
            return (texts[c.window] && texts[c.window][c.kind]) || (c.window + " " + c.kind);  // fora do contrato: dado cru
        }), I18n.tr));
    }

    // Login vencido de uma Conta inativa: estado da renovação automática (acc.renewal.error, código do coletor),
    // frases inteiras com a Conta como %1 e o caminho para reativá-la
    function authErrorText(renewal) {
        var name = cardRoot.accountName;
        var code = renewal ? renewal.error : null;
        if (cardRoot.isActive) return I18n.tr("%1: login expired at the provider. Log in at the provider with this account.", name);  // a ativa não é renovada pelo coletor
        if (!code) return I18n.tr("%1: token expired; automatic renewal will be retried at the next check. To reactivate it now, log in at the provider with this account.", name);
        switch (code) {
        case "revoked": return I18n.tr("%1: login revoked at the provider. Log in at the provider with this account to reactivate it.", name);
        case "cli_missing": return I18n.tr("%1: automatic renewal failed (the provider CLI was not found). Log in at the provider with this account to reactivate it.", name);
        case "binary_missing": return I18n.tr("%1: automatic renewal failed (the Antigravity binary was not found). Log in at the provider with this account to reactivate it.", name);
        case "timeout": return I18n.tr("%1: automatic renewal failed (timed out). It will be retried at the next check; to reactivate it now, log in at the provider with this account.", name);
        case "network": return I18n.tr("%1: automatic renewal failed (network error). It will be retried at the next check; to reactivate it now, log in at the provider with this account.", name);
        default: return I18n.tr("%1: automatic renewal failed. Log in at the provider with this account to reactivate it.", name);
        }
    }

    // Mensagem do erro de consulta pelo `kind` (conjunto fechado do coletor); kind novo = a mensagem do coletor
    function fetchErrorText(err) {
        if (!err) return "";
        switch (err.kind) {
        case "rate_limited": return I18n.tr("Provider rate limit reached (HTTP 429); waiting for the requested pause.");
        case "auth": return cardRoot.authErrorText(cardRoot.accountData?.renewal);
        case "network": return I18n.tr("Failed to query the provider (network unavailable).");
        case "invalid_response": return I18n.tr("The provider answered without the expected usage data.");
        default: return err.message || "";
        }
    }

    // Saúde: palavra + forma (a cor sozinha nunca informa)
    function healthText() {
        var st = cardRoot.healthStatus;
        if (st === "valid") return I18n.tr("Valid");
        if (st === "session_expired") return I18n.tr("Expired");
        if (st === "not_configured") return I18n.tr("Not set up");
        return I18n.tr("Error");
    }

    function healthMark() {
        var st = cardRoot.healthStatus;
        return st === "valid" ? "✓" : st === "session_expired" ? "▲" : st === "not_configured" ? "○" : "■";
    }

    // Situação da consulta: erro (login, limite de requisições, rede), hora dos dados e próxima consulta
    function statusLine() {
        var acc = cardRoot.accountData || {};
        var parts = [];
        if (acc.fetch_error && cardRoot.fetchErrorText(acc.fetch_error)) parts.push("⚠ " + cardRoot.fetchErrorText(acc.fetch_error));
        if (cardRoot.hasNoData) parts.push(I18n.tr("No data from the provider"));
        else if (cardRoot.isStale && acc.fetched_at && !isNaN(Date.parse(acc.fetched_at)))
            parts.push(I18n.tr("Data from %1", ViewPrefs.dateText(Date.parse(acc.fetched_at), cardRoot.nowMs)));
        if (acc.next_check_at && !isNaN(Date.parse(acc.next_check_at)))
            parts.push(I18n.tr("Next check at %1", ViewPrefs.dateText(Date.parse(acc.next_check_at), cardRoot.nowMs)));
        return parts.join(" • ");
    }

    ColumnLayout {
        id: body
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.smallSpacing * 1.5 }
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing * 1.5

            // Anel Duplo da Conta: externo = semanal, interno = Janela Nativa. Restante: o arco mostra o que sobra
            DualRing {
                id: ring
                objectName: "accountRing"
                Accessible.ignored: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.6
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2.6
                Layout.alignment: Qt.AlignTop
                outerPct: ViewPrefs.shownPct(cardRoot.weeklyView.pct, cardRoot.prefs.remaining)
                innerPct: ViewPrefs.shownPct(cardRoot.nativeView.pct, cardRoot.prefs.remaining)
                outerElapsed: cardRoot.weeklyView.elapsed
                innerElapsed: cardRoot.nativeView.elapsed
                outerLevel: cardRoot.weeklyView.level
                innerLevel: cardRoot.nativeView.level
                outerColor: Presets.levelColor(cardRoot.weeklyView.level, cardRoot.accent)
                innerColor: Presets.levelColor(cardRoot.nativeView.level, cardRoot.accent)
                provider: cardRoot.accountData?.provider ?? ""
                sessionState: cardRoot.sessionState
                active: cardRoot.animate
                reducedMotion: cardRoot.reducedMotion
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Math.round(Kirigami.Units.smallSpacing / 2)

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.Label {
                        objectName: "accountName"
                        Accessible.ignored: true
                        Layout.fillWidth: true
                        text: cardRoot.accountName
                        textFormat: Text.PlainText
                        font.bold: true
                        elide: Text.ElideRight
                        color: Presets.ui.fg
                    }

                    // Botão de Ativação Rápida no Sistema (apenas para contas inativas com saúde válida)
                    NotchButton {
                        id: switchAccountButton
                        visible: !cardRoot.isActive && (cardRoot.accountData?.health?.status === "valid")
                        enabled: !cardRoot.isSwitching
                        text: cardRoot.isSwitching ? I18n.tr("Activating...") : I18n.tr("⚡ Activate on System")
                        accent: cardRoot.accent
                        accessibleName: I18n.tr("Activate %1 on the system", cardRoot.accountName)
                        hint: cardRoot.switchError.length > 0 ? cardRoot.switchError
                            : cardRoot.isSwitching ? I18n.tr("Activating account on the system...")
                            : I18n.tr("Activate this account as the default profile for the system CLI")
                        onClicked: cardRoot.switchAccount()
                    }

                    // Badge de Conta Ativa no CLI
                    Rectangle {
                        id: activeCliBadge
                        visible: cardRoot.isActive
                        implicitWidth: activeCliLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                        implicitHeight: activeCliLabel.implicitHeight + Kirigami.Units.smallSpacing
                        radius: 4
                        color: Presets.ui.chip
                        border.width: 1
                        border.color: Kirigami.Theme.highlightColor
                        Accessible.role: Accessible.StaticText
                        Accessible.name: I18n.tr("This account is set as the active account on the system.")

                        QQC2.Label {
                            id: activeCliLabel
                            Accessible.ignored: true
                            anchors.centerIn: parent
                            text: I18n.tr("✓ Active in the CLI")
                            textFormat: Text.PlainText
                            font.bold: true
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            color: Presets.ui.fg
                        }
                        HoverHandler { id: activeHover }
                        PlainTip { visible: activeHover.hovered; text: I18n.tr("This account is set as the active account on the system.") }
                    }

                    Rectangle {
                        id: healthBadge
                        visible: cardRoot.healthStatus !== "valid"  // saúde normal não ocupa espaço; o problema sim
                        implicitWidth: healthLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                        implicitHeight: healthLabel.implicitHeight + Kirigami.Units.smallSpacing
                        radius: 4
                        color: Presets.ui.chip
                        Accessible.role: Accessible.StaticText
                        Accessible.name: I18n.tr("Account health: %1", cardRoot.healthText())
                        Accessible.description: cardRoot.accountData?.health?.message || ""

                        QQC2.Label {
                            id: healthLabel
                            Accessible.ignored: true
                            anchors.centerIn: parent
                            text: cardRoot.healthMark() + " " + cardRoot.healthText()
                            textFormat: Text.PlainText
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            font.bold: true
                            color: Presets.ui.fg
                        }
                        HoverHandler { id: healthHover }
                        PlainTip { visible: healthHover.hovered && Boolean(cardRoot.accountData?.health?.message); text: cardRoot.accountData?.health?.message || "" }
                    }
                }

                QQC2.Label {
                    id: refreshStatusLabel
                    Accessible.ignored: true
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: cardRoot.statusLine()
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: cardRoot.accountData?.fetch_error ? Presets.ui.fg : Presets.ui.muted
                }

                QQC2.Label {
                    objectName: "sessionWord"
                    Accessible.ignored: true
                    Layout.fillWidth: true
                    visible: cardRoot.sessionState !== ""
                    text: NotchModel.sessionWord(cardRoot.sessionState, I18n.tr)
                    textFormat: Text.PlainText
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    font.bold: true
                    color: Presets.ui.fg
                }
            }
        }

        // Medidor 1: Janela Ativa/Horária (título "Janela Ativa (5h)" / "Janela Diária" / "Janela Ativa (%1)")
        WindowRow {
            id: nativeRow
            objectName: "nativeRow"
            Layout.fillWidth: true
            view: cardRoot.nativeView
            remaining: cardRoot.prefs.remaining
            accent: cardRoot.accent
            summary: NotchModel.viewSummary(cardRoot.nativeView, cardRoot.prefs.remaining, I18n.tr)
        }

        // Medidor 2: Janela Semanal (7 dias)
        WindowRow {
            id: weeklyRow
            objectName: "weeklyRow"
            visible: cardRoot.weeklyView.known || cardRoot.nativeView.known  // sem dado algum: uma só linha "Sem dados"
            Layout.fillWidth: true
            view: cardRoot.weeklyView
            remaining: cardRoot.prefs.remaining
            accent: cardRoot.accent
            summary: NotchModel.viewSummary(cardRoot.weeklyView, cardRoot.prefs.remaining, I18n.tr)
        }

        // Nota de mudança de limites (campo opcional "limit_changes", válida por 3 dias)
        QQC2.Label {
            objectName: "limitNote"
            Layout.fillWidth: true
            visible: text.length > 0
            text: cardRoot.limitChangeText(cardRoot.accountData?.limit_changes)
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Presets.ui.fg
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }

        NotchButton {
            id: detailsToggle
            visible: cardRoot.hasDetails
            text: (cardRoot.detailsOpen ? "▾ " : "▸ ") + I18n.tr("History and details")
            accessibleName: I18n.tr("History and details for %1", cardRoot.accountName)
            Accessible.expanded: cardRoot.detailsOpen
            accent: cardRoot.accent
            onClicked: cardRoot.detailsOpen = !cardRoot.detailsOpen
        }

        UsageDetails {
            Layout.fillWidth: true
            visible: cardRoot.detailsOpen && (lines.length > 0 || models.length > 0)
            details: cardRoot.accountData?.usage_details ?? null
        }

        // Histórico de Tokens (campo opcional do contrato v2): o resumo Hoje/Semana/Mês fica sempre à vista,
        // gráfico e períodos só com os detalhes abertos
        TokenHistory {
            Layout.fillWidth: true
            summaryOnly: !cardRoot.detailsOpen
            owner: cardRoot.accountName
            history: cardRoot.accountData?.token_history ?? null
            barColor: cardRoot.accent
        }

        // Convites de Teste Gratuito
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            visible: Boolean((cardRoot.accountData?.free_trial_invites?.available_count || 0) > 0)

            QQC2.Label {
                Accessible.ignored: false
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Presets.ui.fg
                text: {
                    var count = cardRoot.accountData?.free_trial_invites?.available_count || 0;
                    return "✉ " + I18n.trp("%1 free trial invite available", "%1 free trial invites available", count);
                }
            }

            NotchButton {
                id: copyInviteButton
                visible: Boolean(cardRoot.accountData?.free_trial_invites?.invite_url)
                text: cardRoot.copiedFeedback ? I18n.tr("Copied!") : I18n.tr("Copy Link")
                accessibleName: I18n.tr("Copy invite link for %1", cardRoot.accountName)
                accent: cardRoot.accent
                hint: cardRoot.copiedFeedback
                    ? I18n.tr("Link copied to the clipboard!")
                    : I18n.tr("Copy invite link to the clipboard")
                onClicked: {
                    var url = cardRoot.accountData?.free_trial_invites?.invite_url;
                    if (url) {
                        cardRoot.copyToClipboard(url);
                    }
                }
            }
        }
    }
}
