import QtQuick
import QtQuick.Window
import org.kde.layershell as LS

// Só este arquivo importa o módulo layer-shell (LayerShellQt QML): se ele não existir, o Loader de
// FloatingFrame falha e o Notch flutuante se declara indisponível (o pill continua no painel).
// Âncora sempre superior-esquerda + margens = posição local à tela (uniforme nas 4 bordas); zona exclusiva -1
// (o protocolo pede "não me mova": ignora zonas exclusivas de painéis, 0 significaria desviar deles).
Item {
    id: layer
    property FloatingFrame win: null   // tipado: overlay/place/layerReady são propriedades declaradas

    function apply() {
        if (!win) return;
        var a = win.LS.Window;   // atributo anexado: precisa existir antes da janela ser mostrada
        a.scope = "ai-usage-notch";
        a.layer = win.overlay ? LS.Window.LayerOverlay : LS.Window.LayerTop;
        a.exclusionZone = -1;
        a.anchors = LS.Window.AnchorTop | LS.Window.AnchorLeft;
        a.keyboardInteractivity = win.interactive ? LS.Window.KeyboardInteractivityOnDemand : LS.Window.KeyboardInteractivityNone;
        a.margins.left = Math.round(win.place.x);
        a.margins.top = Math.round(win.place.y);
        win.layerReady = true;
    }

    onWinChanged: apply()
    Connections {
        target: layer.win
        function onPlaceChanged() { layer.apply(); }
    }
}
