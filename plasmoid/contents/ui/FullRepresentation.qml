import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Window
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import "Presets.js" as Presets
import "NotchModel.js" as NotchModel
import "ViewPrefs.js" as ViewPrefs
import "I18n.js" as I18n
import "Collector.js" as Collector

// Popup: Notch escuro com um bloco por provedor (ordem e visibilidade configuráveis) e um card por Conta.
// Ações de Conta no popup: Atualizar agora, Configurações (criar, renomear, remover, capturar, login e órfãos
// ficam lá), Ativar no Sistema e Copiar Link (AccountCard), Ver release.
Item {
    id: fullRoot

    property var plasmoidItem: null

    // Preferências de exibição e o relógio de 1 s: só rodam com o popup aberto e o widget visível
    readonly property var prefs: ViewPrefs.config(Plasmoid.configuration)
    property double nowMs: Date.now()
    readonly property bool isOpen: visible && Boolean(plasmoidItem) && plasmoidItem.idleHidden !== true
        && (plasmoidItem.expanded === true || plasmoidItem.inPanel === false)
    readonly property bool reducedMotion: Kirigami.Units.longDuration === 0  // animações desligadas no Plasma
    readonly property color accent: plasmoidItem ? plasmoidItem.accentColor : Kirigami.Theme.highlightColor
    readonly property var providers: NotchModel.popupProviders(plasmoidItem ? plasmoidItem.statusData : null, prefs)
    // Provedor clicado no painel (ticket 48): entrada de compactModel (Conta Ativa no Sistema) ou null (hover, sem item, oculto)
    readonly property var highlight: {
        var hp = plasmoidItem ? plasmoidItem.highlightProvider : "";
        var cm = plasmoidItem && plasmoidItem.compactModel ? plasmoidItem.compactModel : [];
        return hp ? (cm.filter(function (m) { return m.provider === hp; })[0] || null) : null;
    }
    onHighlightChanged: flick.contentY = 0  // o destaque fica no topo da lista: mostra-o ao abrir
    readonly property int accountCount: providers.reduce(function (n, p) { return n + p.accounts.length; }, 0)
    readonly property bool refreshing: Boolean(plasmoidItem && plasmoidItem.isRefreshing)
    readonly property bool spinning: refreshing && isOpen && !reducedMotion  // ícone girando: nunca com o widget oculto

    // Um único executor para todos os cards (Ativar no Sistema, Copiar Link); o resultado volta a quem pediu
    Plasma5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        property var handlers: ({})
        onNewData: (sourceName, data) => {
            var done = handlers[sourceName];
            delete handlers[sourceName];
            disconnectSource(sourceName);
            if (done) done(data);
        }
    }
    TextInput { id: clipHelper; visible: false }

    function runCollector(quotedArgs, onDone) {
        var cmd = Collector.buildCollectorCommand(quotedArgs, Plasmoid.configuration.collectorPath);
        exec.handlers[cmd] = onDone;
        exec.connectSource(cmd);
    }

    function copyText(text) {
        // Qt/QML local e, por garantia, o clipboard do sistema (wl-copy ou xclip), com o texto como argumento posicional
        clipHelper.text = text;
        clipHelper.selectAll();
        clipHelper.copy();
        exec.connectSource("bash -c 'if command -v wl-copy >/dev/null 2>&1; then printf \"%s\" \"$1\" | wl-copy; " +
                           "elif command -v xclip >/dev/null 2>&1; then printf \"%s\" \"$1\" | xclip -selection clipboard; fi' _ " +
                           Collector.shellQuote(text));
    }

    activeFocusOnTab: true
    // Mouse sobre o popup: não fecha por hover enquanto estiver nele
    HoverHandler {
        onHoveredChanged: if (fullRoot.plasmoidItem) fullRoot.plasmoidItem.setPopupHovered(hovered)
    }
    // Foco no popup ao abrir, para o Escape funcionar (precisa de verificação no Plasma real)
    onVisibleChanged: if (visible) fullRoot.forceActiveFocus()
    Keys.onEscapePressed: if (fullRoot.plasmoidItem) fullRoot.plasmoidItem.closePopup()
    // Rolagem pelo teclado com o foco na raiz (sem botão focado)
    function scrollBy(dy) { flick.contentY = Math.max(0, Math.min(Math.max(0, flick.contentHeight - flick.height), flick.contentY + dy)); }
    Keys.onUpPressed: scrollBy(-Kirigami.Units.gridUnit * 2)
    Keys.onDownPressed: scrollBy(Kirigami.Units.gridUnit * 2)
    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_PageUp) scrollBy(-flick.height * 0.9);
        else if (event.key === Qt.Key_PageDown) scrollBy(flick.height * 0.9);
        else if (event.key === Qt.Key_Home) scrollBy(-flick.contentHeight);
        else if (event.key === Qt.Key_End) scrollBy(flick.contentHeight);
        else return;
        event.accepted = true;
    }

    Accessible.role: Accessible.Pane
    Accessible.name: I18n.tr("AI Usage Monitor")

    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.preferredWidth: Kirigami.Units.gridUnit * 25
    Layout.maximumWidth: Kirigami.Units.gridUnit * 35
    Layout.minimumHeight: Kirigami.Units.gridUnit * 22
    Layout.preferredHeight: Kirigami.Units.gridUnit * 28

    function countText(n) { return I18n.trp("%1 account", "%1 accounts", n); }

    // Preferência gravada na configuração do Plasmoid (vale em todo o widget); só valores conhecidos
    function setPref(key, value) {
        if (typeof Plasmoid !== "undefined" && Plasmoid.configuration) Plasmoid.configuration[key] = value;
    }

    // Foco por teclado: rola a lista até o controle focado
    function ensureVisible(it) {
        if (!it) return;
        var inside = false;
        for (var p = it; p; p = p.parent) if (p === flick.contentItem) { inside = true; break; }
        if (!inside) return;
        var y = it.mapToItem(flick.contentItem, 0, 0).y, m = Kirigami.Units.smallSpacing;
        var maxY = Math.max(0, flick.contentHeight - flick.height);
        if (y < flick.contentY) flick.contentY = Math.max(0, y - m);
        else if (y + it.height > flick.contentY + flick.height) flick.contentY = Math.min(maxY, y + it.height - flick.height + m);
    }

    Connections {
        target: fullRoot.Window.window
        function onActiveFocusItemChanged() { fullRoot.ensureVisible(fullRoot.Window.window.activeFocusItem); }
    }

    Timer {
        interval: 1000
        repeat: true
        running: fullRoot.isOpen
        triggeredOnStart: true
        onTriggered: fullRoot.nowMs = Date.now()
    }

    // Fundo sempre escuro; a opacidade é configurável (80 a 100%).
    // PENDÊNCIA PARA O GATE (não verificável sem Plasma real): este popup é um Item com fundo próprio, não um
    // PlasmaExtras.Representation, então o diálogo do Plasma desenha a moldura do tema por trás. Com opacidade
    // < 100% a cor do tema aparece através do fundo (e pode haver moldura dupla). Plasmoid.backgroundHints só
    // controla o fundo do widget na área de trabalho, não o do diálogo do popup; por isso nada é forçado aqui.
    // Todo texto fora dos cards (cuja placa é opaca) usa fg/muted com >= 4,5:1 mesmo no pior caso (piso 80% sobre branco).
    Rectangle {
        objectName: "popupBackground"
        anchors.fill: parent
        radius: 10
        color: Qt.alpha(Presets.ui.panel, fullRoot.prefs.opacity)
        border.width: 1
        border.color: Presets.ui.edge
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing * 2
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                QQC2.Label {
                    Accessible.role: Accessible.Heading
                    text: I18n.tr("AI Usage Monitor")
                    textFormat: Text.PlainText
                    font.bold: true
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.15
                    color: Presets.ui.fg
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                QQC2.Label {
                    objectName: "updatedLabel"
                    // Texto além da animação: a atualização em curso também é dita
                    text: fullRoot.refreshing ? I18n.tr("Updating metrics...")
                        : (fullRoot.plasmoidItem?.lastUpdatedFormatted || I18n.tr("Recently updated"))
                    textFormat: Text.PlainText
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: Presets.ui.muted
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            NotchButton {
                id: refreshButton
                icon.name: "view-refresh"
                text: I18n.tr("Update now")
                display: QQC2.AbstractButton.IconOnly
                accent: fullRoot.accent
                enabled: !fullRoot.refreshing
                hint: fullRoot.refreshing ? I18n.tr("Updating metrics...") : I18n.tr("Update now")
                onClicked: {
                    if (fullRoot.plasmoidItem) {
                        fullRoot.plasmoidItem.refreshCollector();
                    }
                }

                RotationAnimator {
                    target: refreshButton.iconItem
                    from: 0
                    to: 360
                    duration: 1000
                    loops: Animation.Infinite
                    running: fullRoot.spinning
                    onRunningChanged: if (!running) refreshButton.iconItem.rotation = 0
                }
            }

            NotchButton {
                id: configureButton
                icon.name: "configure"
                text: I18n.tr("Settings")
                display: QQC2.AbstractButton.IconOnly
                accent: fullRoot.accent
                hint: I18n.tr("Manage accounts and settings")
                visible: (typeof Plasmoid !== "undefined" && Plasmoid && typeof Plasmoid.internalAction === "function" && Boolean(Plasmoid.internalAction("configure")))
                onClicked: {
                    if (typeof Plasmoid !== "undefined" && Plasmoid.internalAction) {
                        var act = Plasmoid.internalAction("configure");
                        if (act) act.trigger();
                    }
                }
            }
        }

        // Preferências de exibição (valem para o popup, a dica e o painel): usado/restante e contagem/data
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: [
                    { pref: "usageDisplay", value: "used", text: I18n.tr("Used"), hint: I18n.tr("Show how much of the quota has been used") },
                    { pref: "usageDisplay", value: "remaining", text: I18n.tr("Remaining"), hint: I18n.tr("Show how much of the quota is left") },
                    { pref: "resetDisplay", value: "countdown", text: I18n.tr("Countdown"), hint: I18n.tr("Show the time until release") },
                    { pref: "resetDisplay", value: "date", text: I18n.tr("Date"), hint: I18n.tr("Show the release date and time") }
                ]
                delegate: NotchButton {
                    required property var modelData
                    objectName: "pref_" + modelData.value
                    text: modelData.text
                    hint: modelData.hint
                    checkable: true
                    accent: fullRoot.accent
                    checked: modelData.pref === "usageDisplay" ? fullRoot.prefs.remaining === (modelData.value === "remaining")
                                                               : fullRoot.prefs.date === (modelData.value === "date")
                    onClicked: {
                        fullRoot.setPref(modelData.pref, modelData.value);
                        checked = Qt.binding(function () {
                            return modelData.pref === "usageDisplay" ? fullRoot.prefs.remaining === (modelData.value === "remaining")
                                                                     : fullRoot.prefs.date === (modelData.value === "date");
                        });
                    }
                }
            }
        }

        // Atualização em curso: barra indeterminada (parada com animações desligadas; o texto acima informa)
        QQC2.ProgressBar {
            id: refreshProgressBar
            objectName: "refreshBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            indeterminate: !fullRoot.reducedMotion && fullRoot.isOpen
            value: 1
            visible: Boolean(fullRoot.plasmoidItem && (fullRoot.plasmoidItem.isRefreshing || fullRoot.plasmoidItem.isLoading))
            Accessible.ignored: true
        }

        // Novas versões (widget e CLIs); texto simples, o link só abre a página da release validada
        Repeater {
            model: fullRoot.plasmoidItem && fullRoot.plasmoidItem.updateInfo ? fullRoot.plasmoidItem.updateInfo.lines : []
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                QQC2.Label {
                    Layout.fillWidth: true
                    text: "↑ " + modelData.text
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    color: Presets.ui.fg
                }
                NotchButton {
                    visible: modelData.url !== ""
                    text: I18n.tr("View release")
                    accessibleName: I18n.tr("View release: %1", modelData.text)  // distingue as linhas de atualização para leitor de tela
                    hint: I18n.tr("Open the release page in the browser")
                    accent: fullRoot.accent
                    onClicked: Qt.openUrlExternally(modelData.url)
                }
            }
        }

        // Mensagem de erro caso o status.json não tenha sido lido
        Rectangle {
            objectName: "errorBox"
            visible: Boolean(fullRoot.plasmoidItem && fullRoot.plasmoidItem.lastError)
            Layout.fillWidth: true
            implicitHeight: errorLabel.implicitHeight + Kirigami.Units.smallSpacing * 2
            radius: 6
            color: Presets.ui.card
            border.color: Presets.levelColor("critical", fullRoot.accent)
            border.width: 1
            Accessible.role: Accessible.AlertMessage
            Accessible.name: errorLabel.text

            QQC2.Label {
                id: errorLabel
                Accessible.ignored: true
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                text: fullRoot.plasmoidItem ? ("⚠ " + (fullRoot.plasmoidItem.lastError || "")) : ""
                textFormat: Text.PlainText
                color: Presets.ui.fg
                wrapMode: Text.Wrap
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }

        // Blocos por provedor e cards de Contas
        Flickable {
            id: flick
            objectName: "popupFlick"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: list.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            QQC2.ScrollBar.vertical: QQC2.ScrollBar {}

            ColumnLayout {
                id: list
                width: flick.width - Kirigami.Units.gridUnit  // reserva fixa para a barra de rolagem (não muda a largura ao aparecer)
                spacing: Kirigami.Units.smallSpacing * 1.5

                // Provedor clicado no painel: os dois arcos (Janela Nativa e semanal) no topo
                Rectangle {
                    objectName: "highlight"
                    visible: fullRoot.highlight !== null
                    Layout.fillWidth: true
                    implicitHeight: hlRow.implicitHeight + Kirigami.Units.smallSpacing * 3
                    radius: 8
                    color: Presets.ui.card
                    border.width: 1
                    border.color: fullRoot.accent
                    Accessible.role: Accessible.Grouping
                    Accessible.name: fullRoot.highlight ? fullRoot.highlight.name : ""
                    Accessible.description: fullRoot.highlight ? fullRoot.highlight.description : ""

                    RowLayout {
                        id: hlRow
                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.smallSpacing * 1.5
                        spacing: Kirigami.Units.smallSpacing * 2

                        DualRing {
                            objectName: "highlightRing"
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                            Layout.preferredHeight: Kirigami.Units.gridUnit * 4
                            Accessible.ignored: true
                            outerPct: fullRoot.highlight ? ViewPrefs.shownPct(fullRoot.highlight.outerPct, fullRoot.prefs.remaining) : -1
                            innerPct: fullRoot.highlight ? ViewPrefs.shownPct(fullRoot.highlight.innerPct, fullRoot.prefs.remaining) : -1
                            outerElapsed: fullRoot.highlight ? fullRoot.highlight.outerElapsed : -1
                            innerElapsed: fullRoot.highlight ? fullRoot.highlight.innerElapsed : -1
                            outerLevel: fullRoot.highlight ? fullRoot.highlight.outerLevel : ""
                            innerLevel: fullRoot.highlight ? fullRoot.highlight.innerLevel : ""
                            outerColor: Presets.levelColor(outerLevel, fullRoot.accent)
                            innerColor: Presets.levelColor(innerLevel, fullRoot.accent)
                            provider: fullRoot.highlight ? fullRoot.highlight.provider : ""
                            active: fullRoot.isOpen
                            reducedMotion: fullRoot.reducedMotion
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            QQC2.Label {
                                objectName: "highlightName"
                                Accessible.ignored: true
                                Layout.fillWidth: true
                                text: fullRoot.highlight ? fullRoot.highlight.name : ""
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                font.bold: true
                                color: Presets.ui.fg
                            }
                            QQC2.Label {
                                objectName: "highlightNative"
                                Accessible.ignored: true
                                Layout.fillWidth: true
                                text: fullRoot.highlight ? I18n.tr("Native window") + " " + ViewPrefs.pctText(fullRoot.highlight.innerPct, fullRoot.prefs.remaining) : ""
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Presets.ui.fg
                            }
                            QQC2.Label {
                                objectName: "highlightWeekly"
                                Accessible.ignored: true
                                Layout.fillWidth: true
                                text: fullRoot.highlight ? I18n.tr("Weekly") + " " + ViewPrefs.pctText(fullRoot.highlight.outerPct, fullRoot.prefs.remaining) : ""
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Presets.ui.fg
                            }
                        }
                    }
                }

                Repeater {
                    model: fullRoot.providers
                    delegate: ColumnLayout {
                        id: block
                        required property var modelData
                        objectName: "provider_" + modelData.key
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing
                            Accessible.role: Accessible.Heading
                            Accessible.name: block.modelData.accounts.length > 0
                                ? I18n.tr("%1, %2", block.modelData.name, fullRoot.countText(block.modelData.accounts.length)) : block.modelData.name

                            Rectangle {  // logo do provedor: identifica sem depender de cor
                                Accessible.ignored: true
                                implicitWidth: Kirigami.Units.gridUnit * 1.3
                                implicitHeight: implicitWidth
                                radius: width / 2
                                color: Presets.ui.chip
                                ProviderLogo {
                                    anchors.centerIn: parent
                                    width: Math.round(parent.width * 0.65)
                                    height: width
                                    provider: block.modelData.key
                                    color: Presets.ui.fg
                                }
                            }
                            QQC2.Label {
                                Accessible.ignored: true
                                Layout.maximumWidth: flick.width * 0.5  // da Flickable (estável), nunca da largura do próprio bloco (laço de rearranjo)
                                text: block.modelData.name
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                font.bold: true
                                color: Presets.ui.fg
                            }
                            QQC2.Label {
                                Accessible.ignored: true
                                Layout.fillWidth: true
                                // Conta Ativa no Sistema: sem nenhuma marcada, nunca outra conta no lugar
                                text: block.modelData.accounts.length === 0 ? I18n.tr("no accounts")
                                    : block.modelData.hasActive ? fullRoot.countText(block.modelData.accounts.length)
                                    : "○ " + I18n.tr("no account active on the system")
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                font.pointSize: Kirigami.Theme.smallFont.pointSize
                                color: Presets.ui.muted
                            }
                        }

                        Repeater {
                            model: block.modelData.accounts
                            delegate: AccountCard {
                                required property var modelData
                                Layout.fillWidth: true
                                accountData: modelData
                                plasmoidItem: fullRoot.plasmoidItem
                                runCollector: fullRoot.runCollector
                                copyText: fullRoot.copyText
                                nowMs: fullRoot.nowMs
                                prefs: fullRoot.prefs
                                accent: fullRoot.accent
                                animate: fullRoot.isOpen
                                reducedMotion: fullRoot.reducedMotion
                                sessionState: (modelData.isActive === true || modelData.is_active === true) && fullRoot.plasmoidItem
                                    ? NotchModel.sessionState(block.modelData.key, modelData, {
                                        showSession: Plasmoid.configuration.sessionState === true,
                                        sessionOverlay: fullRoot.plasmoidItem.sessionOverlay }) : ""
                                onAccountSwitched: {
                                    if (fullRoot.plasmoidItem && typeof fullRoot.plasmoidItem.loadStatus === "function") {
                                        fullRoot.plasmoidItem.loadStatus();
                                    }
                                }
                            }
                        }
                    }
                }

                // Estados vazios
                QQC2.Label {
                    objectName: "emptyMessage"
                    Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.gridUnit
                    visible: fullRoot.providers.length === 0 || fullRoot.accountCount === 0
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    color: Presets.ui.muted
                    text: fullRoot.providers.length === 0
                        ? I18n.tr("No provider visible in the popup. Choose providers in Settings.")
                        : I18n.tr("No accounts found") + "\n"
                          + I18n.tr("Run 'ai-usage-collector --refresh' to detect local credentials or add accounts in ~/.config/plasma-ai-usage/config.json")
                }
            }
        }
    }
}
