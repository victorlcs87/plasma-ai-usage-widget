import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

// CheckBox cujo rotulo quebra de linha em vez de ser cortado em janelas estreitas (420 px)
QQC2.CheckBox {
    id: control
    Layout.fillWidth: true
    width: parent ? Math.min(implicitWidth, parent.width) : implicitWidth  // em Flow o Layout é ignorado
    contentItem: QQC2.Label {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        verticalAlignment: Text.AlignVCenter
        opacity: control.enabled ? 1 : 0.6
    }
}
