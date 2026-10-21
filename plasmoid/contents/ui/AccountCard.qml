import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as Plasma5Support
import "Presets.js" as Presets
import "NotchModel.js" as NotchModel
import "ViewPrefs.js" as ViewPrefs

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
    readonly property var nativeView: NotchModel.windowView(cardRoot.accountData || {}, cardRoot.accountData?.native_window, "native", cardRoot.prefs, cardRoot.nowMs, cardRoot.safeI18n)
    readonly property var weeklyView: NotchModel.windowView(cardRoot.accountData || {}, cardRoot.accountData?.weekly_window, "weekly", cardRoot.prefs, cardRoot.nowMs, cardRoot.safeI18n)
    readonly property bool hasDetails: Boolean(cardRoot.accountData?.token_history || cardRoot.accountData?.usage_details)
    readonly property string healthStatus: cardRoot.accountData?.health?.status || "unknown"
    readonly property string accountName: cardRoot.accountData?.name || cardRoot.accountData?.label || cardRoot.safeI18n("Conta")

    signal accountSwitched()

    implicitHeight: body.implicitHeight + Kirigami.Units.smallSpacing * 3
    radius: 8
    color: Presets.ui.card
    border.width: cardRoot.isActive ? 2 : 1
    border.color: cardRoot.isActive ? cardRoot.accent : Presets.ui.edge

    Accessible.role: Accessible.Grouping
    Accessible.name: cardRoot.safeI18n("%1, conta %2", Presets.providerInfo(cardRoot.accountData?.provider).name, cardRoot.accountName)
    Accessible.description: [
        cardRoot.isActive ? cardRoot.safeI18n("Ativa no sistema") : "",
        NotchModel.viewSummary(cardRoot.nativeView, cardRoot.prefs.remaining, cardRoot.safeI18n),
        NotchModel.viewSummary(cardRoot.weeklyView, cardRoot.prefs.remaining, cardRoot.safeI18n),
        NotchModel.sessionWord(cardRoot.sessionState, cardRoot.safeI18n)
    ].filter(function (x) { return x; }).join(". ")

    Component.onCompleted: cardRoot.detailsOpen = cardRoot.isActive && cardRoot.hasDetails

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

    function limitChangeText(changes) {
        var now = Date.now();
        changes = (changes || []).filter(function (c) {
            return c && c.window && c.kind && !(c.expires_at && Date.parse(c.expires_at) <= now);
        });
        if (changes.length === 0) return "";
        var names = { native: cardRoot.safeI18n("janela ativa"), weekly: cardRoot.safeI18n("janela semanal") };
        var kinds = {
            added: cardRoot.safeI18n("nova"),
            removed: cardRoot.safeI18n("removida"),
            duration: cardRoot.safeI18n("com duração diferente"),
            early_reset: cardRoot.safeI18n("com reset antecipado")
        };
        return cardRoot.safeI18n("Limites mudaram: %1", changes.map(function (c) {
            return (names[c.window] || c.window) + " " + (kinds[c.kind] || c.kind);
        }).join(", "));
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

    // Saúde: palavra + forma (a cor sozinha nunca informa)
    function healthText() {
        var st = cardRoot.healthStatus;
        if (st === "valid") return cardRoot.safeI18n("Ativa");
        if (st === "session_expired") return cardRoot.safeI18n("Expirada");
        if (st === "not_configured") return cardRoot.safeI18n("Não config.");
        return cardRoot.safeI18n("Erro");
    }

    function healthMark() {
        var st = cardRoot.healthStatus;
        return st === "valid" ? "✓" : st === "session_expired" ? "▲" : st === "not_configured" ? "○" : "■";
    }

    // Situação da consulta: erro (login, limite de requisições, rede), hora dos dados e próxima consulta
    function statusLine() {
        var acc = cardRoot.accountData || {};
        var parts = [];
        if (acc.fetch_error && acc.fetch_error.message) parts.push("⚠ " + acc.fetch_error.message);
        if (cardRoot.hasNoData) parts.push(cardRoot.safeI18n("Sem dados do provedor"));
        else if (cardRoot.isStale && acc.fetched_at && !isNaN(Date.parse(acc.fetched_at)))
            parts.push(cardRoot.safeI18n("Dados de %1", ViewPrefs.dateText(Date.parse(acc.fetched_at), cardRoot.nowMs)));
        if (acc.next_check_at && !isNaN(Date.parse(acc.next_check_at)))
            parts.push(cardRoot.safeI18n("Próxima consulta às %1", ViewPrefs.dateText(Date.parse(acc.next_check_at), cardRoot.nowMs)));
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
                letter: Presets.providerInfo(cardRoot.accountData?.provider).letter
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
                        text: cardRoot.isSwitching ? cardRoot.safeI18n("Ativando...") : cardRoot.safeI18n("⚡ Ativar no Sistema")
                        accent: cardRoot.accent
                        hint: cardRoot.switchError.length > 0 ? cardRoot.switchError
                            : cardRoot.isSwitching ? cardRoot.safeI18n("Ativando conta no sistema...")
                            : cardRoot.safeI18n("Ativar esta conta como perfil padrão no CLI do sistema")
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
                        Accessible.name: cardRoot.safeI18n("Esta conta está configurada como a conta ativa no sistema.")

                        QQC2.Label {
                            id: activeCliLabel
                            Accessible.ignored: true
                            anchors.centerIn: parent
                            text: cardRoot.safeI18n("✓ Ativa no CLI")
                            textFormat: Text.PlainText
                            font.bold: true
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            color: Presets.ui.fg
                        }
                        HoverHandler { id: activeHover }
                        QQC2.ToolTip.visible: activeHover.hovered
                        QQC2.ToolTip.text: cardRoot.safeI18n("Esta conta está configurada como a conta ativa no sistema.")
                    }

                    Rectangle {
                        id: healthBadge
                        visible: cardRoot.healthStatus !== "valid"  // saúde normal não ocupa espaço; o problema sim
                        implicitWidth: healthLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                        implicitHeight: healthLabel.implicitHeight + Kirigami.Units.smallSpacing
                        radius: 4
                        color: Presets.ui.chip
                        Accessible.role: Accessible.StaticText
                        Accessible.name: cardRoot.safeI18n("Saúde da conta: %1", cardRoot.healthText())
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
                        QQC2.ToolTip.visible: healthHover.hovered && Boolean(cardRoot.accountData?.health?.message)
                        QQC2.ToolTip.text: cardRoot.accountData?.health?.message || ""
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
                    text: NotchModel.sessionWord(cardRoot.sessionState, cardRoot.safeI18n)
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
            summary: NotchModel.viewSummary(cardRoot.nativeView, cardRoot.prefs.remaining, cardRoot.safeI18n)
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
            summary: NotchModel.viewSummary(cardRoot.weeklyView, cardRoot.prefs.remaining, cardRoot.safeI18n)
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
            text: (cardRoot.detailsOpen ? "▾ " : "▸ ") + cardRoot.safeI18n("Histórico e detalhes")
            Accessible.name: cardRoot.safeI18n("Histórico e detalhes")
            Accessible.expanded: cardRoot.detailsOpen
            accent: cardRoot.accent
            onClicked: cardRoot.detailsOpen = !cardRoot.detailsOpen
        }

        UsageDetails {
            Layout.fillWidth: true
            visible: cardRoot.detailsOpen && (lines.length > 0 || models.length > 0)
            details: cardRoot.accountData?.usage_details ?? null
        }

        // Histórico de Tokens (campo opcional do contrato v2)
        TokenHistory {
            Layout.fillWidth: true
            visible: cardRoot.detailsOpen && Boolean(history)
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
                    return "✉ " + (count === 1
                        ? cardRoot.safeI18n("1 convite de teste gratuito disponível")
                        : cardRoot.safeI18n("%1 convites de teste gratuito disponíveis", count));
                }
            }

            NotchButton {
                id: copyInviteButton
                visible: Boolean(cardRoot.accountData?.free_trial_invites?.invite_url)
                text: cardRoot.copiedFeedback ? cardRoot.safeI18n("Copiado!") : cardRoot.safeI18n("Copiar Link")
                accent: cardRoot.accent
                hint: cardRoot.copiedFeedback
                    ? cardRoot.safeI18n("Link copiado para a Área de Transferência!")
                    : cardRoot.safeI18n("Copiar link de convite para a Área de Transferência")
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
