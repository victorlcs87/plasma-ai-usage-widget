import QtQuick
import QtQuick.Window
import "I18n.js" as I18n

// Janela do Notch flutuante (ticket 41), base do pílula e do popup. Sem layer-shell (X11 e fallback) é uma
// janela comum sem moldura, sempre no topo, fora da barra de tarefas e sem strut (não reserva área, então
// painéis que aparecem/somem não a deslocam). Com layer-shell (Wayland), FloatingLayer.qml, carregado só ali,
// aplica âncora/margens/zona exclusiva na mesma janela; ela só é mostrada depois disso (layerReady).
Window {
    id: win

    property var host: null                      // FloatingNotch
    property rect place: Qt.rect(0, 0, 100, 40)  // posição e tamanho, locais à tela
    property bool wanted: false
    property bool interactive: false             // aceita foco de teclado (popup, pílula)
    property bool overlay: false                 // camada acima das janelas (layer-shell)
    property bool layerReady: !(host && host.useLayer)
    readonly property var scr: host ? host.screenInfo : null

    title: I18n.tr("AI Usage Monitor")
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
    color: "transparent"
    screen: host ? host.screenObj : null
    x: (scr ? scr.virtualX : 0) + place.x
    y: (scr ? scr.virtualY : 0) + place.y
    width: Math.max(1, place.width)
    height: Math.max(1, place.height)
    visible: wanted && layerReady && scr !== null

    Loader {
        active: win.host !== null && win.host.useLayer
        source: "FloatingLayer.qml"
        onLoaded: (item as FloatingLayer).win = win
        onStatusChanged: if (status === Loader.Error && win.host) win.host.layerFailed()
    }
}
