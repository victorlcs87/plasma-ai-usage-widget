import QtQuick

// Anel Duplo: externo = semanal, interno = Janela Nativa. pct < 0 = desconhecido (só trilho).
// elapsed < 0 = sem marca de tempo decorrido.
Item {
    id: ring

    property real outerPct: -1
    property real innerPct: -1
    property real outerElapsed: -1
    property real innerElapsed: -1
    property color outerColor: "#8a9099"
    property color innerColor: "#8a9099"
    property string letter: ""

    implicitWidth: 24
    implicitHeight: 24

    onOuterPctChanged: canvas.requestPaint()
    onInnerPctChanged: canvas.requestPaint()
    onOuterElapsedChanged: canvas.requestPaint()
    onInnerElapsedChanged: canvas.requestPaint()
    onOuterColorChanged: canvas.requestPaint()
    onInnerColorChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        function arc(ctx, cx, cy, r, lw, pct, elapsed, color) {
            var start = -Math.PI / 2;
            ctx.lineWidth = lw;
            ctx.lineCap = "round";
            ctx.strokeStyle = "rgba(255,255,255,0.16)";
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, 2 * Math.PI);
            ctx.stroke();
            if (pct > 0) {
                ctx.strokeStyle = color;
                ctx.beginPath();
                ctx.arc(cx, cy, r, start, start + 2 * Math.PI * Math.min(1, pct / 100));
                ctx.stroke();
            }
            if (elapsed >= 0) {  // marca radial do tempo decorrido
                var a = start + 2 * Math.PI * Math.min(1, elapsed);
                ctx.lineWidth = 1.5;
                ctx.lineCap = "butt";
                ctx.strokeStyle = "#ffffff";
                ctx.beginPath();
                ctx.moveTo(cx + (r - lw / 2 - 1) * Math.cos(a), cy + (r - lw / 2 - 1) * Math.sin(a));
                ctx.lineTo(cx + (r + lw / 2 + 1) * Math.cos(a), cy + (r + lw / 2 + 1) * Math.sin(a));
                ctx.stroke();
            }
        }

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var s = Math.min(width, height);
            var lw = Math.max(2, s * 0.1);
            var cx = width / 2, cy = height / 2;
            var rOuter = s / 2 - lw / 2 - 1.5;
            var rInner = rOuter - lw - Math.max(1.5, s * 0.05);
            arc(ctx, cx, cy, rOuter, lw, ring.outerPct, ring.outerElapsed, ring.outerColor);
            arc(ctx, cx, cy, rInner, lw, ring.innerPct, ring.innerElapsed, ring.innerColor);
        }
    }

    // Inicial do provedor: distingue os anéis sem depender de cor
    Text {
        anchors.centerIn: parent
        visible: ring.width >= 22 && ring.letter.length > 0
        text: ring.letter
        color: "#c9ced6"
        font.pixelSize: Math.round(ring.width * 0.26)
        font.bold: true
        textFormat: Text.PlainText
    }
}
