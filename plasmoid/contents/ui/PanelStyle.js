.pragma library

// Estilos do painel (ticket 32): validação da configuração, o que cada estilo desenha e a geometria.
// Puro (testável sem Plasma). Cor SÓ pelo nível do contrato: aqui só se escolhe e se mede.

var styles = ["pill", "ring", "text", "bar"];     // pill = padrão
var modes = ["ring", "ringpct", "pct"];            // só anel (padrão) | anel + % | só %
var centers = ["logo", "pct", "logopct"];          // centro do anel
var SCALE = [80, 160], MARGIN = [0, 16];
var DEFAULT_SCALE = 100, DEFAULT_MARGIN = 4;       // 4 px = Kirigami.Units.smallSpacing de hoje

function pick(list, v, def) { return typeof v === "string" && list.indexOf(v) >= 0 ? v : def; }
// Fora da faixa, não numérico ou NaN: padrão (nunca clamp silencioso)
function intIn(v, range, def) {
    return typeof v === "number" && isFinite(v) && v >= range[0] && v <= range[1] ? Math.round(v) : def;
}

// `c` = Plasmoid.configuration (ou qualquer objeto): valores inválidos caem no padrão
function config(c) {
    c = c || {};
    return {
        style: pick(styles, c.panelStyle, "pill"),
        mode: pick(modes, c.panelMode, "ring"),
        center: pick(centers, c.ringCenter, "logo"),
        scale: intIn(c.metricSize, SCALE, DEFAULT_SCALE) / 100,
        margin: intIn(c.panelMargin, MARGIN, DEFAULT_MARGIN)
    };
}

var RANK = { critical: 3, warning: 2, normal: 1, "": 0 };

// Janela de destaque de um provedor (a mais urgente entre as conhecidas; empate = maior %).
// Sem dado em nenhuma: pct -1 (mostrado como "—", nunca 0%).
function headline(m) {
    var best = { pct: -1, level: "" };
    [{ pct: m.innerPct, level: m.innerLevel }, { pct: m.outerPct, level: m.outerLevel }].forEach(function (w) {
        if (w.pct < 0) return;
        if (best.pct < 0 || RANK[w.level] > RANK[best.level] || (RANK[w.level] === RANK[best.level] && w.pct > best.pct)) best = w;
    });
    return best;
}

function pctText(pct) { return pct < 0 ? "—" : Math.round(pct) + "%"; }

// Forma do nível além da cor: normal ●, atenção ▲, crítico ■, sem nível ○
function levelMark(level) {
    return level === "critical" ? "■" : level === "warning" ? "▲" : level === "normal" ? "●" : "○";
}

// O que cada estilo desenha por provedor: gráfico (anéis ou barras), cabeça (inicial + marca de nível) e %
function parts(style, mode) {
    return {
        graphic: style !== "text" && mode !== "pct",
        head: style === "text" || style === "bar" || mode === "pct",
        pct: mode !== "ring"
    };
}

// Marca de nível: Text mostra sempre (exceto só %); nos demais só atenção/crítico (forma além da cor)
function markVisible(style, mode, level) {
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

function size(o, unit, f, ip) {
    var p = parts(o.style, o.mode), lh = Math.ceil(f * 1.3), box = Math.ceil(f * 1.2), markW = Math.ceil(f);
    var aW = 0, aH = 0, n = 0;
    if (p.head) { aW += box + markW; aH = lh; n++; }  // inicial (círculo da sessão) + marca de nível
    if (p.graphic) { aW += o.style === "bar" ? 2 * barWidth(unit) + 4 : unit; aH = Math.max(aH, unit); n++; }
    aW += Math.max(0, n - 1) * o.gap;
    var pw = adv("100%", f), w, h;
    if (o.vertical) { w = Math.max(aW, p.pct ? pw : 0); h = aH + (p.pct ? o.gap + lh : 0); }
    else { w = aW + (p.pct ? o.gap + pw : 0); h = Math.max(aH, p.pct ? lh : 0); }
    return { w: w + 2 * ip, h: h + 2 * ip, pctW: pw, lh: lh, box: box, markW: markW, unit: unit, fontPx: f, ip: ip };
}

// Tamanho (igual para todos os provedores) de um item numa espessura de painel `cross` (px).
// o: {style, mode, vertical, pad, gap, base, scale, minUnit}. Fonte e unidade encolhem até caber na
// espessura (sem corte); com cross = 0 sai o tamanho mínimo.
function layout(o, cross) {
    var ip = o.style === "ring" ? 2 : 0;  // estilo Ring: cada item tem fundo escuro próprio
    var avail = Math.max(0, cross - 2 * o.pad - 2 * ip);
    var unit = Math.min(Math.round(o.base * o.scale), Math.max(o.minUnit, avail));
    for (var f = Math.max(8, Math.round(unit * 0.5)); ; f--) {
        var s = size(o, unit, f, ip);
        if (f <= 7 || (o.vertical ? s.w : s.h) <= avail + 2 * ip) return s;
    }
}
