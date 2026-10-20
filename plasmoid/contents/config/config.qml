import QtQuick

import org.kde.plasma.plasmoid
import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: i18n("Contas e Configurações")
        icon: "preferences-system-network"
        source: "configGeneral.qml"
    }
}
