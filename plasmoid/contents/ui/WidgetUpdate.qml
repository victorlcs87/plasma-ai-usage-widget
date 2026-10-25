import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import "Presets.js" as Presets
import "I18n.js" as I18n

// Atualização do Widget (ticket 77, ADR-0014): botão + confirmação inline + progresso + erro + recarga.
// Reutilizável: basta instanciar `WidgetUpdate { plasmoidItem: root }` em qualquer menu. Todo o estado e as ações vivem no
// main.qml (widgetUpdate, checkWidgetUpdate, askWidgetUpdate, cancelWidgetUpdate, startWidgetUpdate, reloadWidget);
// aqui só se mostra e se encaminha o clique. Nada roda sozinho.
ColumnLayout {
    id: wu

    property var plasmoidItem: null
    property color accent: Kirigami.Theme.highlightColor

    readonly property var upd: plasmoidItem && plasmoidItem.widgetUpdate ? plasmoidItem.widgetUpdate : ({ state: "idle", result: "" })
    readonly property string phase: upd.state || "idle"
    readonly property string version: plasmoidItem ? plasmoidItem.widgetUpdateVersion || "" : ""
    readonly property string current: plasmoidItem ? plasmoidItem.widgetVersion || "" : ""
    readonly property bool cooldown: Boolean(plasmoidItem && plasmoidItem.widgetCheckCooldown)
    readonly property bool busy: phase === "buscando" || phase === "atualizando"
    property bool reloadConfirming: false

    Layout.fillWidth: true
    spacing: Kirigami.Units.smallSpacing
    onPhaseChanged: reloadConfirming = false

    function cancelAsk() { if (plasmoidItem) plasmoidItem.cancelWidgetUpdate(); wu.forceActiveFocus(); }
    function cancelReload() { reloadConfirming = false; wu.forceActiveFocus(); }

    function stepName(step) {
        return step === "venv" ? I18n.tr("Preparing the environment") : step === "download" ? I18n.tr("Downloading the package")
            : step === "install" ? I18n.tr("Installing the package") : step === "link" ? I18n.tr("Creating the shortcut")
            : step === "verify" ? I18n.tr("Verifying the installation") : step === "plasmoid_hash" ? I18n.tr("Reading the widget checksum")
            : step === "plasmoid_download" ? I18n.tr("Downloading the widget") : step === "plasmoid_verify" ? I18n.tr("Verifying the widget download")
            : step === "plasmoid_install" ? I18n.tr("Installing the widget") : "";
    }
    readonly property string causeText: {
        var c = upd.cause;
        return c === "python_indisponivel" ? I18n.tr("Python 3 with venv support is not available. Install it and try again.")
            : c === "rede" ? I18n.tr("Could not download the update. Check your internet connection and try again.")
            : c === "versao_inexistente" ? I18n.tr("This version is not available yet. Try again later.")
            : c === "permissao" ? I18n.tr("Permission denied while writing to the installation folders.")
            : c === "conflito_em_local_bin" ? I18n.tr("Another file already exists in ~/.local/bin and was not overwritten.")
            : c === "verificacao" ? I18n.tr("The download did not pass the integrity check. Nothing was changed.")
            : c === "sem_hash" ? I18n.tr("This collector cannot verify the widget download, so the update was not applied. Update manually from the release page.")
            : c === "kpackagetool" ? I18n.tr("kpackagetool6 could not install the widget package. The collector was updated; update the widget manually from the release page.")
            : phase === "erro" ? I18n.tr("The update failed.") : "";
    }
    // Resultado da última busca (sem versão nova)
    readonly property string note: phase !== "idle" ? ""
        : upd.result === "atual" ? I18n.tr("You already have the latest version.")
        : upd.result === "indisponivel" ? I18n.tr("Could not check for updates right now. Try again later.")
        : upd.result === "desligada" ? I18n.tr("Update checks are turned off in the settings.") : ""
    readonly property string primaryText: phase === "buscando" ? I18n.tr("Checking for updates…")
        : phase === "atualizando" ? I18n.tr("Updating the widget…")
        : phase === "erro" ? I18n.tr("Try again")
        : version !== "" ? I18n.tr("Update to v%1", version) : I18n.tr("Check for updates")

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        visible: wu.phase !== "concluido"

        NotchButton {
            id: primary
            objectName: "widgetUpdateButton"
            accent: wu.accent
            text: wu.primaryText
            icon.name: wu.version !== "" ? "update-none" : "view-refresh"
            enabled: !wu.busy && wu.phase !== "confirmando" && (wu.version !== "" || !wu.cooldown)
            hint: wu.version !== "" ? I18n.tr("Asks for confirmation first; nothing is changed until you confirm.")
                : I18n.tr("Looks for a newer release on GitHub. Nothing is installed.")
            onClicked: {
                if (!wu.plasmoidItem) return;
                if (wu.version !== "") wu.plasmoidItem.askWidgetUpdate();
                else wu.plasmoidItem.checkWidgetUpdate();
            }
        }
        QQC2.Label {
            objectName: "widgetUpdateNote"
            visible: text !== ""
            Layout.fillWidth: true
            text: wu.note
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
    }

    // Confirmação inline (Dialog em popup do Plasma é frágil): foco inicial em Cancelar; Esc cancela
    ColumnLayout {
        id: confirm
        objectName: "widgetUpdateConfirm"
        visible: wu.phase === "confirmando"
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        Accessible.role: Accessible.Grouping
        Accessible.name: confirmTitle.text
        onVisibleChanged: if (visible) cancelAskButton.forceActiveFocus()
        Keys.onEscapePressed: wu.cancelAsk()
        QQC2.Label {
            id: confirmTitle
            objectName: "widgetUpdateConfirmTitle"
            Layout.fillWidth: true
            text: I18n.tr("Update the widget from v%1 to v%2?", wu.current, wu.version)
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.bold: true
            color: Presets.ui.fg
        }
        QQC2.Label {
            objectName: "widgetUpdateConfirmDetails"
            Layout.fillWidth: true
            text: I18n.tr("The collector and the widget package will be downloaded from GitHub Releases and the widget package is checked against a checksum.") + "\n"
                + I18n.tr("No sudo is used. The widget keeps running the old version until you reload it.")
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.fg
        }
        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            NotchButton {
                id: cancelAskButton
                objectName: "widgetUpdateCancelButton"
                accent: wu.accent
                text: I18n.tr("Cancel")
                hint: I18n.tr("Closes this question without changing anything.")
                onClicked: wu.cancelAsk()
            }
            NotchButton {
                objectName: "widgetUpdateConfirmButton"
                accent: wu.accent
                text: I18n.tr("Update")
                hint: I18n.tr("Downloads and installs the update now.")
                onClicked: if (wu.plasmoidItem) { wu.forceActiveFocus(); wu.plasmoidItem.startWidgetUpdate(); }
            }
        }
    }

    // Progresso: barra indeterminada + nome da etapa (o botão acima fica desligado)
    ColumnLayout {
        objectName: "widgetUpdateProgress"
        visible: wu.phase === "atualizando"
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        QQC2.ProgressBar {
            objectName: "widgetUpdateBar"
            Layout.fillWidth: true
            indeterminate: true
            value: 1
            Accessible.name: I18n.tr("Updating the widget…")
        }
        QQC2.Label {
            objectName: "widgetUpdateStep"
            visible: text !== ""
            Layout.fillWidth: true
            text: wu.stepName(wu.upd.step)
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
    }

    // Falha: causa classificada em texto claro, detalhe e etapa onde parou
    ColumnLayout {
        objectName: "widgetUpdateError"
        visible: wu.phase === "erro"
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        Accessible.role: Accessible.AlertMessage
        Accessible.name: wu.causeText
        QQC2.Label {
            objectName: "widgetUpdateCause"
            Layout.fillWidth: true
            text: "⚠ " + wu.causeText
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.bold: true
            color: Presets.ui.fg
        }
        QQC2.Label {
            objectName: "widgetUpdateMessage"
            visible: text !== ""
            Layout.fillWidth: true
            text: (wu.upd.message ? I18n.tr("Details: %1", wu.upd.message) : "")
                + (wu.upd.failedStep && wu.stepName(wu.upd.failedStep) !== "" ? (wu.upd.message ? "\n" : "") + I18n.tr("Stopped during: %1", wu.stepName(wu.upd.failedStep)) : "")
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: Presets.ui.muted
        }
    }

    // Concluído: o QML antigo segue em memória; recarregar é decisão do usuário, com aviso do efeito
    ColumnLayout {
        objectName: "widgetUpdateDone"
        visible: wu.phase === "concluido"
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        Accessible.role: Accessible.Grouping
        Accessible.name: doneLabel.text
        QQC2.Label {
            id: doneLabel
            objectName: "widgetUpdateDoneText"
            Layout.fillWidth: true
            text: "✓ " + I18n.tr("Updated to v%1. Reload the widget to start using it.", wu.upd.to || wu.version)
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.bold: true
            color: Presets.ui.fg
        }
        NotchButton {
            objectName: "widgetReloadButton"
            visible: !wu.reloadConfirming
            accent: wu.accent
            text: I18n.tr("Reload the widget")
            hint: I18n.tr("Asks for confirmation first; the Plasma shell is not restarted until you confirm.")
            onClicked: wu.reloadConfirming = true
        }
        ColumnLayout {
            objectName: "widgetReloadConfirm"
            visible: wu.reloadConfirming
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Accessible.role: Accessible.Grouping
            Accessible.name: I18n.tr("Reload the widget?")
            onVisibleChanged: if (visible) cancelReloadButton.forceActiveFocus()
            Keys.onEscapePressed: wu.cancelReload()
            QQC2.Label {
                objectName: "widgetReloadDetails"
                Layout.fillWidth: true
                text: I18n.tr("This restarts the Plasma shell: panels and widgets disappear for a few seconds and come back. Nothing is lost.")
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: Presets.ui.fg
            }
            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                NotchButton {
                    id: cancelReloadButton
                    objectName: "widgetReloadCancelButton"
                    accent: wu.accent
                    text: I18n.tr("Not now")
                    hint: I18n.tr("Closes this question; the old version keeps running until you reload.")
                    onClicked: wu.cancelReload()
                }
                NotchButton {
                    objectName: "widgetReloadConfirmButton"
                    accent: wu.accent
                    text: I18n.tr("Reload now")
                    hint: I18n.tr("Restarts the Plasma shell now.")
                    onClicked: if (wu.plasmoidItem) { wu.reloadConfirming = false; wu.plasmoidItem.reloadWidget(); }
                }
            }
        }
    }
}
