import QtQuick

// Logo do Provedor: silhueta SVG (logo-<provedor>.svg, ver LOGOS.md) pintada com `color` (tema/nível).
// Canvas (não MultiEffect/shader): funciona em qualquer renderizador, inclusive o software do harness.
// Decorativo: o nome acessível do provedor vem de quem usa. Provedor desconhecido mostra "?".
Item {
    id: logo

    property string provider: ""
    property color color: "#c9ced6"
    readonly property bool known: provider === "claude" || provider === "codex" || provider === "gemini"
    readonly property url file: known ? Qt.resolvedUrl("logo-" + provider + ".svg") : ""

    implicitWidth: 16
    implicitHeight: 16
    Accessible.ignored: true

    onFileChanged: if (known) canvas.loadImage(file)
    onColorChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        visible: logo.known
        Component.onCompleted: if (logo.known) loadImage(logo.file)
        onImageLoaded: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            if (!logo.known || !isImageLoaded(logo.file)) return;
            var s = Math.min(width, height);
            ctx.drawImage(logo.file, (width - s) / 2, (height - s) / 2, s, s);
            ctx.globalCompositeOperation = "source-in";  // fica só a silhueta, na cor pedida
            ctx.fillStyle = logo.color;
            ctx.fillRect(0, 0, width, height);
        }
    }
    Text {
        anchors.centerIn: parent
        visible: !logo.known
        text: "?"
        color: logo.color
        font.pixelSize: Math.max(7, Math.round(logo.height * 0.8))
        font.bold: true
        textFormat: Text.PlainText
    }
}
