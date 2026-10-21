import QtQuick

import org.kde.plasma.plasmoid
import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: i18n("Accounts and Settings")
        icon: "preferences-system-network"
        source: "configGeneral.qml"
    }
}
