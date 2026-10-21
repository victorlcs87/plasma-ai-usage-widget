// Único mecanismo de tradução do Plasmoid. NÃO é .pragma library de propósito: assim o `i18n` do
// KLocalizedContext (contexto do componente que importa) é visível aqui. Sem `i18n` (harness
// qml6 offscreen, testes) cai no texto-fonte (inglês) com os %N substituídos, sem rich text.
// Extração: tools/i18n.py reconhece tr/trc/trp (e i18n/i18nc/i18np) com literais.

function fmt(s, args) {
    return String(s).replace(/%(\d)/g, function (m, d) {
        var v = args[Number(d) - 1];
        return v === undefined ? m : String(v);
    });
}

// tr("Hello %1", name)
function tr(text, a, b, c, d) {
    if (!text) return "";
    if (typeof i18n === "function") {
        if (d !== undefined) return i18n(text, a, b, c, d);
        if (c !== undefined) return i18n(text, a, b, c);
        if (b !== undefined) return i18n(text, a, b);
        if (a !== undefined) return i18n(text, a);
        return i18n(text);
    }
    return fmt(text, [a, b, c, d]);
}

// trc("context for translators", "Hello %1", name)
function trc(ctx, text, a, b, c) {
    if (!text) return "";
    if (typeof i18nc === "function") {
        if (c !== undefined) return i18nc(ctx, text, a, b, c);
        if (b !== undefined) return i18nc(ctx, text, a, b);
        if (a !== undefined) return i18nc(ctx, text, a);
        return i18nc(ctx, text);
    }
    return fmt(text, [a, b, c]);
}

// trp("%1 account", "%1 accounts", n): %1 é sempre a contagem
function trp(one, many, n, a, b) {
    if (typeof i18np === "function") {
        if (b !== undefined) return i18np(one, many, n, a, b);
        if (a !== undefined) return i18np(one, many, n, a);
        return i18np(one, many, n);
    }
    return fmt(Number(n) === 1 ? one : many, [n, a, b]);
}

// 12400 -> "12,4k" (pt_BR) / "12.4k" (en): casa decimal pelo locale, para o ponto nunca parecer separador de milhar
function compactNumber(n) {
    n = Number(n) || 0;
    var units = [[1e9, "B"], [1e6, "M"], [1e3, "k"]];
    for (var i = 0; i < units.length; i++)
        if (n >= units[i][0]) return (n / units[i][0]).toLocaleString(Qt.locale(), "f", 1) + units[i][1];
    return String(n);
}
