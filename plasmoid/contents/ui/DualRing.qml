import QtQuick
import "Presets.js" as Presets
import QtQuick.Window

// Anel Duplo: externo = semanal, interno = Janela Nativa. pct < 0 = desconhecido (só trilho).
// elapsed < 0 = sem marca de tempo decorrido.
Item {
    id: ring

    property real outerPct: -1
    property real innerPct: -1
    property real outerElapsed: -1
    property real innerElapsed: -1
    property color outerColor: Presets.neutral
    property color innerColor: Presets.neutral
    property string outerLevel: ""
    property string innerLevel: ""
    property string letter: ""
    // Estado da Sessão: "busy" = arco girando, "waiting" = anel âmbar pulsando. reducedMotion = formas
    // estáticas (arco parado, anel fixo), sem nenhuma animação.
    property string sessionState: ""
    property bool reducedMotion: false
    // Sem animar (nem gastar CPU) com o widget oculto
    property bool active: true  // false com o widget oculto por ociosidade (idleHidden)
    readonly property bool shown: active && visible && (Window.window ? Window.window.visible : true)

    implicitWidth: 24
    implicitHeight: 24

    onOuterPctChanged: canvas.requestPaint()
    onInnerPctChanged: canvas.requestPaint()
    onOuterElapsedChanged: canvas.requestPaint()
    onInnerElapsedChanged: canvas.requestPaint()
    onOuterColorChanged: canvas.requestPaint()
    onInnerColorChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
    onOuterLevelChanged: canvas.requestPaint()
    onInnerLevelChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        function arc(ctx, cx, cy, r, lw, pct, elapsed, color, level) {
            var start = -Math.PI / 2;
            ctx.lineWidth = lw;
            ctx.lineCap = level === "critical" || level === "warning" ? "butt" : "round";
            ctx.strokeStyle = "rgba(255,255,255,0.16)";
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, 2 * Math.PI);
            ctx.stroke();
            if (pct > 0) {
                // Forma além da cor: warning = traços longos, critical = traços curtos
                ctx.setLineDash(level === "critical" ? [lw * 0.9, lw * 0.9] : level === "warning" ? [lw * 3, lw * 1.2] : []);
                ctx.strokeStyle = color;
                ctx.beginPath();
                ctx.arc(cx, cy, r, start, start + 2 * Math.PI * Math.min(1, pct / 100));
                ctx.stroke();
                ctx.setLineDash([]);
            }
            if (pct === 0 && (level === "critical" || level === "warning")) {  // 0% (ex.: restante esgotado): ponto no topo mantém a forma do nível
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(cx, cy - r, lw * 0.7, 0, 2 * Math.PI);
                ctx.fill();
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
            var lw = Math.max(1.75, s * 0.085);
            var cx = width / 2, cy = height / 2;
            var rOuter = s / 2 - lw / 2 - 1;
            var rInner = rOuter - lw - Math.max(1.25, s * 0.045);
            arc(ctx, cx, cy, rOuter, lw, ring.outerPct, ring.outerElapsed, ring.outerColor, ring.outerLevel);
            arc(ctx, cx, cy, rInner, lw, ring.innerPct, ring.innerElapsed, ring.innerColor, ring.innerLevel);
        }
    }

    // Centro: inicial do provedor (distingue os anéis sem depender de cor), % ou os dois. Sem espaço
    // para o % legível, cai na inicial; "pct" sem dado mostra "—", nunca 0.
    property string centerMode: "logo"  // "logo" | "pct" | "logopct"
    property string centerPct: ""
    property bool centerDim: false  // dado obsoleto: % do centro esmaecido
    readonly property bool roomPct: width >= 28
    readonly property bool showPct: centerMode !== "logo" && roomPct && centerPct.length > 0
    readonly property bool showLetter: letter.length > 0 && width >= 20 && (centerMode !== "pct" || !showPct)
    Column {
        anchors.centerIn: parent
        Text {
            Accessible.ignored: true
            visible: ring.showLetter
            anchors.horizontalCenter: parent.horizontalCenter
            text: ring.letter
            color: Presets.ui.letter
            font.pixelSize: Math.max(8, Math.round(ring.width * (ring.showPct ? 0.2 : 0.3)))
            font.bold: true
            textFormat: Text.PlainText
        }
        Text {
            Accessible.ignored: true
            opacity: ring.centerDim ? 0.6 : 1
            visible: ring.showPct
            anchors.horizontalCenter: parent.horizontalCenter
            text: ring.centerPct
            color: "#ffffff"
            font.pixelSize: Math.max(7, Math.round(ring.width * (ring.showLetter ? 0.2 : 0.26)))
            font.bold: true
            textFormat: Text.PlainText
        }
    }

    SessionMark {
        anchors.fill: parent
        sessionState: ring.sessionState
        reducedMotion: ring.reducedMotion
        shown: ring.shown
    }
}
