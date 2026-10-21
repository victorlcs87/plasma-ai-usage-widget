.pragma library

// Predefinições da cor de destaque do Notch. "plasma" = cor de realce do Plasma (padrão).
var accents = [
    { key: "plasma", name: "Realce do Plasma", color: "" },
    { key: "pink", name: "Rosa", color: "#ff5fa2" },
    { key: "red", name: "Vermelho", color: "#ff5c5c" },
    { key: "orange", name: "Laranja", color: "#ff9f43" },
    { key: "yellow", name: "Amarelo", color: "#ffd84d" },
    { key: "green", name: "Verde", color: "#4cd964" },
    { key: "teal", name: "Teal", color: "#2dd4bf" },
    { key: "blue", name: "Azul", color: "#4da3ff" },
    { key: "indigo", name: "Índigo", color: "#7b83ff" },
    { key: "purple", name: "Roxo", color: "#b57bff" },
    { key: "white", name: "Branco", color: "#f2f2f2" },
    { key: "off", name: "Desligado", color: "#9aa0a6" }
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
