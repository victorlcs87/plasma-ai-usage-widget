.pragma library
.import "Presets.js" as Presets

// Preferências de exibição (ticket 33), valendo em todo o widget: popup, dica e painel.
// Puro (testável sem Plasma). Valor inválido ou fora da faixa = padrão (nunca clamp silencioso).

// Piso 80: com fundo claro atrás do popup, o texto direto sobre o fundo mantém >= 4,5:1 (teste de contraste)
var OPACITY = [80, 100], DEFAULT_OPACITY = 100;

function pick(list, v, def) { return typeof v === "string" && list.indexOf(v) >= 0 ? v : def; }

// `c` = Plasmoid.configuration (ou qualquer objeto)
function config(c) {
    c = c || {};
    var op = c.popupOpacity;
    var hidden = String(c.popupHiddenProviders || "").split(",").map(function (k) { return k.trim(); }).filter(function (k) { return k; });
    return {
        remaining: pick(["used", "remaining"], c.usageDisplay, "used") === "remaining",
        date: pick(["countdown", "date"], c.resetDisplay, "countdown") === "date",
        opacity: (typeof op === "number" && isFinite(op) && op >= OPACITY[0] && op <= OPACITY[1] ? Math.round(op) : DEFAULT_OPACITY) / 100,
        order: Presets.normalizeOrder(c.popupProviderOrder).filter(function (k) { return hidden.indexOf(k) === -1; })
    };
}

// Percentual exibido: usado ou restante (inteiro); desconhecido (< 0) continua -1, nunca vira 100%
function shownPct(pct, remaining) {
    if (!(pct >= 0)) return -1;
    var p = Math.round(Math.min(100, pct));
    return remaining ? 100 - p : p;
}

function pctText(pct, remaining) {
    var p = shownPct(pct, remaining);
    return p < 0 ? "—" : p + "%";
}

function two(n) { return (n < 10 ? "0" : "") + n; }

// Contagem regressiva que anda a cada segundo: "3d 5h 12m", "2h 05m 09s", "12m 03s", "9s"
function countdown(sec) {
    sec = Math.max(0, Math.floor(sec));
    var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    if (d > 0) return d + "d " + h + "h " + two(m) + "m";
    if (h > 0) return h + "h " + two(m) + "m " + two(s) + "s";
    if (m > 0) return m + "m " + two(s) + "s";
    return s + "s";
}

// Data/hora local do reset: só a hora no mesmo dia, "dd/MM HH:mm" nos outros
function dateText(ms, nowMs) {
    var d = new Date(ms), n = new Date(nowMs);
    var hm = two(d.getHours()) + ":" + two(d.getMinutes());
    return d.toDateString() === n.toDateString() ? hm : two(d.getDate()) + "/" + two(d.getMonth() + 1) + " " + hm;
}
