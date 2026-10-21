import QtQuick
import "Presets.js" as Presets
import "PanelStyle.js" as PanelStyle

// Barras verticais do estilo Bar: esquerda = semanal, direita = Janela Nativa. pct < 0 = desconhecido
// (só trilho). elapsed < 0 = sem marcador de tempo decorrido (traço horizontal na barra).
// Nível além da cor: warning = traços longos, critical = traços curtos (como nos anéis).
Item {
    id: bars

    property real outerPct: -1
    property real innerPct: -1
    property real outerElapsed: -1
    property real innerElapsed: -1
    property color outerColor: Presets.neutral
    property color innerColor: Presets.neutral
    property string outerLevel: ""
    property string innerLevel: ""

    readonly property real barW: PanelStyle.barWidth(height)
    implicitWidth: PanelStyle.barsWidth(height)
    implicitHeight: 22

    onOuterPctChanged: canvas.requestPaint()
    onInnerPctChanged: canvas.requestPaint()
    onOuterElapsedChanged: canvas.requestPaint()
    onInnerElapsedChanged: canvas.requestPaint()
    onOuterColorChanged: canvas.requestPaint()
    onInnerColorChanged: canvas.requestPaint()
    onOuterLevelChanged: canvas.requestPaint()
    onInnerLevelChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent

        function bar(ctx, x, w, h, pct, elapsed, color, level) {
            ctx.lineWidth = w;
            ctx.lineCap = "butt";
            ctx.strokeStyle = "rgba(255,255,255,0.16)";
            ctx.beginPath();
            ctx.moveTo(x, h);
            ctx.lineTo(x, 0);
            ctx.stroke();
            if (pct > 0) {
                ctx.setLineDash(level === "critical" ? [w * 0.9, w * 0.9] : level === "warning" ? [w * 3, w * 1.2] : []);
                ctx.strokeStyle = color;
                ctx.beginPath();
                ctx.moveTo(x, h);
                ctx.lineTo(x, h - h * Math.min(1, pct / 100));
                ctx.stroke();
                ctx.setLineDash([]);
            }
            if (elapsed >= 0) {  // marcador do tempo decorrido
                var y = h - h * Math.min(1, elapsed);
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = "#ffffff";
                ctx.beginPath();
                ctx.moveTo(x - w / 2 - 1, y);
                ctx.lineTo(x + w / 2 + 1, y);
                ctx.stroke();
            }
        }

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var w = bars.barW;
            bar(ctx, w / 2 + 1, w, height, bars.outerPct, bars.outerElapsed, bars.outerColor, bars.outerLevel);
            bar(ctx, w * 1.5 + 3, w, height, bars.innerPct, bars.innerElapsed, bars.innerColor, bars.innerLevel);
        }
    }
}
