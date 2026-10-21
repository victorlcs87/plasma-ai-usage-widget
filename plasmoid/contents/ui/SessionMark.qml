import QtQuick
import QtQuick.Window

// Estado da Sessão sobre um círculo (anel ou inicial): "busy" = arco girando, "waiting" = anel âmbar
// pulsando. reducedMotion = formas estáticas (arco parado, anel fixo), sem nenhuma animação.
Item {
    id: mark

    property string sessionState: ""
    property bool reducedMotion: false
    property bool shown: true  // false com o widget oculto: nenhuma animação roda

    // Ocupada: arco de 100° no contorno externo, girando
    Canvas {
        id: spinner
        anchors.fill: parent
        visible: mark.sessionState === "busy"
        antialiasing: true
        onVisibleChanged: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var s = Math.min(width, height);
            // fio fino na folga de 1 px fora do anel externo: nao cobre a cor de nivel
            ctx.lineWidth = 1.2;
            ctx.lineCap = "round";
            ctx.strokeStyle = "#ffffff";
            ctx.beginPath();
            ctx.arc(width / 2, height / 2, s / 2 - 0.7, 0, 1.75);
            ctx.stroke();
        }
        RotationAnimator on rotation {
            from: 0; to: 360; duration: 1100; loops: Animation.Infinite
            running: spinner.visible && mark.shown && !mark.reducedMotion
        }
    }

    // Aguardando o usuário: anel âmbar pulsando
    Rectangle {
        id: pulse
        anchors.fill: parent
        visible: mark.sessionState === "waiting"
        color: "transparent"
        radius: width / 2
        border.width: Math.max(2, mark.width * 0.1)
        border.color: "#f5a524"
        SequentialAnimation on opacity {
            loops: Animation.Infinite
            running: pulse.visible && mark.shown && !mark.reducedMotion
            NumberAnimation { from: 1; to: 0.25; duration: 700; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.25; to: 1; duration: 700; easing.type: Easing.InOutSine }
        }
    }
}
