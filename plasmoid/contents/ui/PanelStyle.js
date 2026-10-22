.pragma library
.import "ViewPrefs.js" as ViewPrefs

// Estilos do painel (ticket 32): validação da configuração, o que cada estilo desenha e a geometria.
// Puro (testável sem Plasma). Cor SÓ pelo nível do contrato: aqui só se escolhe e se mede.

var styles = ["pill", "ring", "text", "bar"];     // pill = padrão
var modes = ["ring", "ringpct", "pct"];            // só anel (padrão) | anel + % | só %
var centers = ["logo", "pct", "logopct"];          // centro do anel
var SCALE = [80, 160], MARGIN = [0, 16];
var DEFAULT_SCALE = 100, AUTO_MARGIN = -1;         // margem -1 = automática (Kirigami.Units.smallSpacing)
var RING_PCT_UNIT = 28;                            // menor anel que comporta o % no centro

function pick(list, v, def) { return typeof v === "string" && list.indexOf(v) >= 0 ? v : def; }
// Fora da faixa, não numérico ou NaN: padrão (nunca clamp silencioso)
function intIn(v, range, def) {
    return typeof v === "number" && isFinite(v) && v >= range[0] && v <= range[1] ? Math.round(v) : def;
}

// No estilo Text o "só o gráfico" não existe (o estilo é % + ponto): vale como "gráfico e %"
function modeFor(style, mode) { return style === "text" && mode === "ring" ? "ringpct" : mode; }

// `c` = Plasmoid.configuration (ou qualquer objeto): valores inválidos caem no padrão
function config(c) {
    c = c || {};
    var style = pick(styles, c.panelStyle, "pill");
    return {
        style: style,
        mode: modeFor(style, pick(modes, c.panelMode, "ring")),
        center: pick(centers, c.ringCenter, "logo"),
        scale: intIn(c.metricSize, SCALE, DEFAULT_SCALE) / 100,
        margin: intIn(c.panelMargin, MARGIN, AUTO_MARGIN)
    };
}

var RANK = { critical: 3, warning: 2, normal: 1, "": 0 };

// Janela de destaque de um provedor: a mais urgente entre as conhecidas (maior nível; empate = maior %).
// Sem dado em nenhuma: pct -1 (mostrado como "—", nunca 0%).
function headline(m) {
    var best = { pct: -1, level: "" };
    [{ pct: m.innerPct, level: m.innerLevel }, { pct: m.outerPct, level: m.outerLevel }].forEach(function (w) {
        if (w.pct < 0) return;
        if (best.pct < 0 || RANK[w.level] > RANK[best.level] || (RANK[w.level] === RANK[best.level] && w.pct > best.pct)) best = w;
    });
    return best;
}

function pctText(pct, remaining) { return ViewPrefs.pctText(pct, remaining); }  // "—" sem dado, nunca 0%

// Forma do nível além da cor: normal ●, atenção ▲, crítico ■, sem nível ○
function levelMark(level) {
    return level === "critical" ? "■" : level === "warning" ? "▲" : level === "normal" ? "●" : "○";
}

// O que cada estilo desenha por provedor: gráfico (anéis ou barras), cabeça (inicial + marca de nível) e %
function parts(style, mode) {
    mode = modeFor(style, mode);
    return {
        graphic: style !== "text" && mode !== "pct",
        head: style === "text" || style === "bar" || mode === "pct",
        pct: mode !== "ring"
    };
}

// Marca de nível: Text mostra sempre (exceto só %); nos demais só atenção/crítico (forma além da cor)
function markVisible(style, mode, level) {
    mode = modeFor(style, mode);
    return (style === "text" && mode !== "pct") || level === "warning" || level === "critical";
}

var WIDTH = { " ": 0.3, "%": 0.95, "—": 1 };
// Largura estimada (em em) de um texto curto; folga de 5% para fontes mais largas
function adv(s, px) {
    var w = 0;
    for (var i = 0; i < s.length; i++) w += s[i] >= "0" && s[i] <= "9" ? 0.6 : (WIDTH[s[i]] || 0.75);
    return Math.ceil(w * px * 1.05);
}

function barWidth(unit) { return Math.max(3, Math.round(unit * 0.2)); }
function barsWidth(unit) { return 2 * barWidth(unit) + 4; }

function size(o, unit, f, ip) {
    var p = parts(o.style, o.mode), lh = Math.ceil(f * 1.3), box = o.vertical ? Math.ceil(f * 1.2) : unit, markW = Math.ceil(f);
    var aW = 0, aH = 0, n = 0;
    if (p.head) { aW += box + markW; aH = Math.max(lh, box); n++; }  // logo (círculo da sessão): na altura da unidade; em painel vertical a largura limita, fica no tamanho da fonte + marca de nível
    if (p.graphic) { aW += o.style === "bar" ? barsWidth(unit) : unit; aH = Math.max(aH, unit); n++; }
    aW += Math.max(0, n - 1) * o.gap;
    var pw = adv("100%", f), w, h;
    if (o.vertical) { w = Math.max(aW, p.pct ? pw : 0); h = aH + (p.pct ? o.gap + lh : 0); }
    else { w = aW + (p.pct ? o.gap + pw : 0); h = Math.max(aH, p.pct ? lh : 0); }
    return { w: w + 2 * ip, h: h + 2 * ip, pctW: pw, lh: lh, box: box, markW: markW, unit: unit, fontPx: f, ip: ip };
}

function ringStyle(style) { return style === "pill" || style === "ring"; }
// Centro com % pede um anel de pelo menos RING_PCT_UNIT (senão o % não é legível)
function needsPct(o) { return ringStyle(o.style) && o.mode !== "pct" && o.center !== "logo"; }
function floorUnit(o) { return needsPct(o) ? Math.max(o.minUnit, RING_PCT_UNIT) : o.minUnit; }

// Tamanho (igual para todos os provedores) de um item numa espessura de painel `cross` (px).
// o: {style, mode, center, vertical, pad, gap, base, scale, minUnit}. Fonte e unidade encolhem até caber
// na espessura (sem corte); o anel nunca fica abaixo de floorUnit.
function layout(o, cross) {
    var ip = o.style === "ring" ? 2 : 0;  // estilo Ring: cada item tem fundo escuro próprio
    var avail = Math.max(0, cross - 2 * o.pad - 2 * ip);
    // fill (painel): o anel ocupa a espessura disponível; a escala só reduz (nunca passa de 100% dela)
    var fl = floorUnit(o), want = o.fill && ringStyle(o.style) ?Math.max(Math.round(avail * Math.min(1, o.scale)), fl) : Math.max(Math.round(o.base * o.scale), needsPct(o) ? fl : 0);
    var unit = Math.min(want, Math.max(fl, avail));
    for (var f = Math.max(8, Math.round(unit * 0.5)); ; f--) {
        var s = size(o, unit, f, ip);
        if (f <= 7 || (o.vertical ? s.w : s.h) <= avail + 2 * ip) return s;
    }
}

// Menor espessura em que o estilo cabe sem corte
function minCross(o) {
    var base = floorUnit(o) + 2 * o.pad + (o.style === "ring" ? 4 : 0);
    var s = layout(o, base);
    return Math.max(base, (o.vertical ? s.w : s.h) + 2 * o.pad);
}

var CHAIN = { bar: ["bar", "text", "pill"], text: ["text", "pill"], ring: ["ring", "pill"], pill: ["pill"] };

// Estilo e centro realmente usados na espessura `cross`: se o pedido não cabe, degrada (centro -> logo,
// depois Bar -> Text -> Pílula) em vez de cortar. Na espessura mínima de nenhum, fica o mais compacto.
// `along` (comprimento disponível, px; 0/ausente = sem limite) e `runFn(o)` (comprimento que a variante pede)
// fazem o mesmo pela LARGURA (painel horizontal) ou ALTURA (vertical) disponível.
function effective(o, cross, along, runFn) {
    var cands = [];
    CHAIN[o.style].forEach(function (st) {
        [o.center, "logo"].forEach(function (c) { if (!cands.some(function (x) { return x.style === st && x.center === c; })) cands.push({ style: st, center: c }); });
    });
    // Último recurso antes de encolher a escala: pílula só com os anéis (sem % ao lado e sem selos); o chamador
    // esconde os selos quando `lean`. Texto só com % (mode "pct") não tem anel: mantém o modo.
    cands.push({ style: "pill", center: "logo", mode: o.mode === "pct" ? "pct" : "ring", lean: true });
    for (var i = 0; i < cands.length; i++) {
        var oo = {};
        for (var k in o) oo[k] = o[k];
        oo.style = cands[i].style; oo.center = cands[i].center;
        if (cands[i].mode) oo.mode = cands[i].mode;
        oo.lean = cands[i].lean === true;
        if (cross >= minCross(oo) && !(along > 0 && runFn && runFn(oo) > along)) return cands[i];
    }
    return cands[cands.length - 1];
}
