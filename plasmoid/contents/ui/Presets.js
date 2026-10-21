.pragma library

// Predefinições da cor de destaque do Notch (os nomes traduzidos ficam em configGeneral.qml). "plasma" = cor de realce do Plasma (padrão).
var accents = [
    { key: "plasma", color: "" },
    { key: "pink", color: "#ff5fa2" },
    { key: "red", color: "#ff5c5c" },
    { key: "orange", color: "#ff9f43" },
    { key: "yellow", color: "#ffd84d" },
    { key: "green", color: "#4cd964" },
    { key: "teal", color: "#2dd4bf" },
    { key: "blue", color: "#4da3ff" },
    { key: "indigo", color: "#7b83ff" },
    { key: "purple", color: "#b57bff" },
    { key: "white", color: "#f2f2f2" },
    { key: "off", color: "#9aa0a6" }
];

var providers = [
    { key: "claude", name: "Claude", letter: "C" },
    { key: "codex", name: "Codex", letter: "X" },
    { key: "gemini", name: "Gemini", letter: "G" }
];

// Cor de destaque efetiva; highlight vem do tema (Kirigami.Theme.highlightColor)
function accentColor(key, highlight) {
    for (var i = 0; i < accents.length; i++)
        if (accents[i].key === key && accents[i].color) return accents[i].color;
    return highlight;
}

// Ordem salva ("claude,codex") -> lista completa e válida (desconhecidos saem, faltantes entram no fim)
function normalizeOrder(csv) {
    var out = [], seen = {};
    String(csv || "").split(",").forEach(function (k) {
        k = k.trim();
        for (var i = 0; i < providers.length; i++)
            if (providers[i].key === k && !seen[k]) { seen[k] = true; out.push(k); }
    });
    providers.forEach(function (p) { if (!seen[p.key]) out.push(p.key); });
    return out;
}

function providerInfo(key) {
    for (var i = 0; i < providers.length; i++) if (providers[i].key === key) return providers[i];
    return { key: key, name: key, letter: "?" };
}

// Nível de alerta do contrato -> cor. Sem nível/obsoleto/sem dado: neutro, nunca verde falso.
var neutral = "#8a9099", warning = "#f5a524", critical = "#ff4d4f";
function levelColor(level, accent) {
    if (level === "critical") return critical;
    if (level === "warning") return warning;
    if (level === "normal") return accent;
    return neutral;
}

// Contraste (WCAG) das marcas de atualização sobre a pílula escura: o glifo usa a cor da pílula e o
// preenchimento é clareado até chegar a 4,5:1 contra ela (vale também para o ponto, só forma/cor).
var PILL_RGB = [0x15 / 255, 0x17 / 255, 0x1b / 255];
function _chan(v) { return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
function luminance(rgb) { return 0.2126 * _chan(rgb[0]) + 0.7152 * _chan(rgb[1]) + 0.0722 * _chan(rgb[2]); }
function contrast(a, b) {
    var la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
function _hex(rgb) {
    return "#" + rgb.map(function (v) { var h = Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16); return h.length < 2 ? "0" + h : h; }).join("");
}
// r,g,b em 0..1 (Qt color); devolve "#rrggbb" com >= min (padrão 4,5; 3 para formas como o acento) sobre a pílula
function onPill(r, g, b, min) {
    var c = [r, g, b];
    min = min || 4.5;
    for (var i = 0; i < 30 && contrast(c, PILL_RGB) < min; i++)
        c = c.map(function (v) { return v + (1 - v) * 0.1; });
    return _hex(c);
}

// Paleta fixa do Notch (sempre escuro, independente do tema): fundo, cartão, borda, texto, texto secundário
// e botão. Texto sobre o cartão >= 4,5:1.
var ui = { panel: "#15171b", card: "#1d2026", edge: "#2f333b", fg: "#e6e8eb", muted: "#b4bac2", chip: "#2a2e36", letter: "#c9ced6" };
