.pragma library

// Notch flutuante (ticket 41): configuração validada e geometria por borda, tudo em coordenadas LOCAIS à tela
// (0,0 = canto superior esquerdo do monitor). Puro (testável sem Plasma). Valor inválido = padrão (nunca clamp
// silencioso na configuração); a POSIÇÃO é sempre reconstruída contra a geometria atual (clamp), então monitor
// removido ou resolução menor nunca deixam o Notch fora da tela.

var EDGES = ["top", "bottom", "left", "right"];
var SIZE = [80, 160], OFFSET = [-20000, 20000];
var GAP = 4;        // folga entre o Notch e a borda
var MARGIN = 8;     // folga mínima do popup até as bordas da tela
var SNAP = 12;      // px: perto do centro, gruda nele

function intIn(v, r, def) { return typeof v === "number" && isFinite(v) && v >= r[0] && v <= r[1] ? Math.round(v) : def; }
function vertical(edge) { return edge === "left" || edge === "right"; }

// `c` = Plasmoid.configuration. offset = px a partir do CENTRO da borda (0 = centralizado), um por borda.
function config(c) {
    c = c || {};
    var edge = typeof c.floatEdge === "string" && EDGES.indexOf(c.floatEdge) >= 0 ? c.floatEdge : "top";
    var cap = function (e) { return e.charAt(0).toUpperCase() + e.slice(1); };
    var offsets = {};
    EDGES.forEach(function (e) { offsets[e] = intIn(c["floatOffset" + cap(e)], OFFSET, 0); });
    return {
        enabled: c.floatingNotch === true,
        edge: edge,
        vertical: vertical(edge),
        scale: intIn(c.floatSize, SIZE, 100) / 100,
        offsets: offsets,
        snap: c.floatSnap !== false,
        screen: typeof c.floatScreen === "string" ? c.floatScreen.trim() : ""
    };
}

// Índice da tela: a de nome `name`; senão `fallback` (a do widget) se existir; senão a primária (0)
function pickScreen(screens, name, fallback) {
    screens = screens || [];
    for (var i = 0; i < screens.length; i++) if (name && screens[i].name === name) return i;
    return fallback >= 0 && fallback < screens.length ? fallback : 0;
}

function clampOffset(edge, offset, size, scr) {
    var along = vertical(edge) ? scr.h : scr.w, len = vertical(edge) ? size.h : size.w;
    var max = Math.max(0, along - len) / 2;   // limite simétrico a partir do centro
    return Math.max(-max, Math.min(max, typeof offset === "number" && isFinite(offset) ? offset : 0));
}

function snapOffset(offset, snap) { return snap && Math.abs(offset) <= SNAP ? 0 : offset; }

// Retângulo do Notch preso à borda; `offset` já clampado na saída
function pillRect(edge, offset, size, scr) {
    var off = clampOffset(edge, offset, size, scr), w = size.w, h = size.h;
    var x, y;
    if (vertical(edge)) {
        y = Math.round((scr.h - h) / 2 + off);
        x = edge === "left" ? GAP : scr.w - w - GAP;
    } else {
        x = Math.round((scr.w - w) / 2 + off);
        y = edge === "top" ? GAP : scr.h - h - GAP;
    }
    return { x: Math.max(0, x), y: Math.max(0, y), w: w, h: h, offset: off };
}

// Popup ancorado no Notch, abrindo para DENTRO da tela e sempre dentro dela (tamanho limitado ao espaço livre)
function popupRect(edge, pill, want, scr) {
    var w = Math.max(1, Math.min(want.w, scr.w - 2 * MARGIN)), h = Math.max(1, Math.min(want.h, scr.h - 2 * MARGIN));
    var x, y;
    if (vertical(edge)) {
        var room = edge === "left" ? scr.w - (pill.x + pill.w) - GAP - MARGIN : pill.x - GAP - MARGIN;
        w = Math.max(1, Math.min(w, room));
        x = edge === "left" ? pill.x + pill.w + GAP : pill.x - GAP - w;
        y = pill.y + pill.h / 2 - h / 2;
    } else {
        var roomH = edge === "top" ? scr.h - (pill.y + pill.h) - GAP - MARGIN : pill.y - GAP - MARGIN;
        h = Math.max(1, Math.min(h, roomH));
        y = edge === "top" ? pill.y + pill.h + GAP : pill.y - GAP - h;
        x = pill.x + pill.w / 2 - w / 2;
    }
    x = Math.max(MARGIN, Math.min(scr.w - w - MARGIN, x));
    y = Math.max(MARGIN, Math.min(scr.h - h - MARGIN, y));
    return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
}
