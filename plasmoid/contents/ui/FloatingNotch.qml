import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
import "FloatingGeometry.js" as FG
import "PanelStyle.js" as PanelStyle

// Notch flutuante (ticket 41, opcional, desligado por padrão): pílula e popup em janelas próprias presas a uma
// das quatro bordas, independentes do painel. Toda a posição vem de FloatingGeometry.js (puro, testado); a
// posição é uma por borda (floatOffsetTop/Bottom/Left/Right, px a partir do centro) e a configuração é a única
// fonte: o arraste só mexe em `liveOffset` (local) e grava ao soltar.
Item {
    id: fn

    property var plasmoidItem: null
    property bool forceLayer: false     // testes: exercita o caminho layer-shell fora do Wayland
    property bool layerBroken: false
    function layerFailed() { layerBroken = true; }

    readonly property var cfg: FG.config(Plasmoid.configuration)
    readonly property bool useLayer: forceLayer || Qt.platform.pluginName.indexOf("wayland") === 0
    readonly property var screens: Qt.application.screens
    property string widgetScreenName: fn.Window.window && fn.Window.window.screen ? fn.Window.window.screen.name : ""
    readonly property int screenIdx: FG.pickScreen(screens, cfg.screen, FG.pickScreen(screens, widgetScreenName, 0))
    readonly property var screenObj: screens.length > 0 ? screens[screenIdx] : null
    property var screenInfo: screenObj   // geometria usada nas contas (os testes simulam telas pequenas por aqui)
    readonly property var scrRect: ({ w: screenInfo ? screenInfo.width : 0, h: screenInfo ? screenInfo.height : 0 })
    readonly property var pillWindow: pillWin
    readonly property var popupWindow: popupWin

    // Indisponível = sem tela ou layer-shell que não carregou: o widget segue como pílula no painel
    // Com floatScreen definido só a instância que mora naquela tela mostra o Notch (dois widgets não se sobrepõem
    // por monitor); a de outra tela mantém a pílula no painel. Dois widgets na MESMA tela ainda se sobrepõem.
    readonly property bool ownsScreen: cfg.screen === "" || widgetScreenName === "" || widgetScreenName === cfg.screen
    readonly property bool available: plasmoidItem !== null && screenInfo !== null && ownsScreen && !(useLayer && layerBroken)

    // Tamanho escolhido (floatSize) no lugar do tamanho do painel; estilo/modo/centro/margem do painel valem
    readonly property var panelCfg: { var p = PanelStyle.config(Plasmoid.configuration); p.scale = cfg.scale; return p; }

    property real liveOffset: NaN       // só durante o arraste
    readonly property real offset: isNaN(liveOffset) ? cfg.offsets[cfg.edge] : liveOffset
    readonly property var pillSize: ({ w: pillWin.want.width, h: pillWin.want.height })
    readonly property var pill: FG.pillRect(cfg.edge, offset, pillSize, scrRect)
    readonly property var popup: FG.popupRect(cfg.edge, pill, { w: popupWin.want.width, h: popupWin.want.height }, scrRect)

    function cap(e) { return e.charAt(0).toUpperCase() + e.slice(1); }
    function commit(off, snap) {
        var c = FG.clampOffset(cfg.edge, off, pillSize, scrRect);
        var v = Math.round(snap ? FG.snapOffset(c, cfg.snap) : c);
        Plasmoid.configuration["floatOffset" + cap(cfg.edge)] = v;
        liveOffset = NaN;
    }
    function dragBy(d) {
        if (Math.abs(d) < 1 && isNaN(liveOffset)) return;
        liveOffset = FG.clampOffset(cfg.edge, offset + d, pillSize, scrRect);
    }
    function dragEnd() { if (!isNaN(liveOffset)) commit(liveOffset, true); }  // só o arraste gruda no centro (teclado anda de 8 em 8 px)
    function nudge(d) { commit(offset + d, false); }
    function recenter() { liveOffset = NaN; Plasmoid.configuration["floatOffset" + cap(cfg.edge)] = 0; }

    FloatingPillWindow {
        id: pillWin
        host: fn
        wanted: fn.available
        place: Qt.rect(fn.pill.x, fn.pill.y, fn.pill.w, fn.pill.h)
    }

    FloatingPopupWindow {
        id: popupWin
        host: fn
        wanted: fn.available && fn.plasmoidItem !== null && fn.plasmoidItem.open === true
        place: Qt.rect(fn.popup.x, fn.popup.y, fn.popup.w, fn.popup.h)
    }
}
