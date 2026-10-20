import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore

Item {
    id: compactRoot

    property var plasmoidItem: null

    Layout.minimumWidth: Kirigami.Units.iconSizes.small
    Layout.minimumHeight: Kirigami.Units.iconSizes.small
    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
    Layout.preferredHeight: Kirigami.Units.iconSizes.medium

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor

        onClicked: {
            if (compactRoot.plasmoidItem) {
                compactRoot.plasmoidItem.expanded = !compactRoot.plasmoidItem.expanded;
            } else if (typeof root !== "undefined" && root.expanded !== undefined) {
                root.expanded = !root.expanded;
            }
        }
    }

    Kirigami.Icon {
        id: mainIcon
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height) - Kirigami.Units.smallSpacing
        height: width
        source: {
            if (compactRoot.plasmoidItem && compactRoot.plasmoidItem.Plasmoid) {
                return compactRoot.plasmoidItem.Plasmoid.icon;
            }
            if (typeof Plasmoid !== "undefined" && Plasmoid.icon) {
                return Plasmoid.icon;
            }
            return "view-split-left-right";
        }
        active: mouseArea.containsMouse
    }

    // Badge de status de uso / saúde no canto inferior direito
    Rectangle {
        id: statusDot
        width: Math.max(8, Kirigami.Units.smallSpacing * 1.8)
        height: width
        radius: width / 2
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 1

        color: {
            var pct = compactRoot.plasmoidItem ? (compactRoot.plasmoidItem.maxUsagePercent || 0.0) : 0.0;
            if (pct < 70) return "#27ae60"; // Verde
            if (pct <= 90) return "#f39c12"; // Amarelo
            return "#e74c3c"; // Vermelho
        }
        border.color: Kirigami.Theme.backgroundColor
        border.width: 1.5
    }

    // Badge numérico de convites no canto superior direito
    Rectangle {
        id: inviteBadge
        visible: Boolean(compactRoot.plasmoidItem && compactRoot.plasmoidItem.totalInvites > 0)
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: -1

        implicitHeight: Math.max(14, Kirigami.Units.gridUnit * 0.9)
        implicitWidth: Math.max(inviteLabel.implicitWidth + 6, implicitHeight)
        radius: implicitHeight / 2
        color: "#d35400"
        border.color: Kirigami.Theme.backgroundColor
        border.width: 1

        QQC2.Label {
            id: inviteLabel
            anchors.centerIn: parent
            text: String(compactRoot.plasmoidItem ? compactRoot.plasmoidItem.totalInvites : 0)
            font.bold: true
            font.pointSize: Kirigami.Theme.smallFont.pointSize * 0.75
            color: "white"
        }
    }
}
