import QtQuick
import QtQuick.Controls as QQC2

// Dica sempre em texto puro: o texto pode vir de dados (mensagem de saúde, stderr do coletor, datas) e a
// ToolTip padrão interpreta HTML (AutoText).
QQC2.ToolTip {
    id: tip
    contentItem: QQC2.Label {
        text: tip.text
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }
}
