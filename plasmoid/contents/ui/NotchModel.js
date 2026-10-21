.pragma library
.import "Presets.js" as Presets

// Modelo do Notch compacto: função pura sobre status.json + config (testável sem Plasma).
// `tr` = safeI18n do chamador.

function visibleProviders(cfg) {
    var hidden = String(cfg.hiddenProviders || "").split(",");
    return Presets.normalizeOrder(cfg.providerOrder).filter(function (k) { return hidden.indexOf(k) === -1; });
}

// Conta Ativa no Sistema (CONTEXT.md); sem nenhuma marcada, null: nunca outra conta no lugar
function activeAccount(agent) {
    var accs = (agent && agent.accounts) || [];
    for (var i = 0; i < accs.length; i++) {
        if (accs[i].isActive === true || accs[i].is_active === true) return accs[i];
    }
    return null;
}

// Só ISO 8601 ("2026-..T.."): Date.parse("5") não é data
function parseIso(v) { return typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) ? Date.parse(v) : NaN; }

function isNum(v) { return typeof v === "number" && isFinite(v); }

// Percentual da janela, ou -1 (desconhecido): sem dado, não numérico, obsoleto com liberação já
// passada, ou 0% sem nenhum dado de janela (defesa contra 0% falso)
function windowPct(acc, win, resetKey) {
    if (!acc || !win || acc.no_data === true || !isNum(win.usage_percentage)) return -1;
    var p = win.usage_percentage;
    var reset = parseIso(win[resetKey]);
    if (acc.stale === true && !isNaN(reset) && reset <= Date.now()) return -1;
    if (p === 0 && isNaN(reset) && !(win.window_seconds > 0) && !(win.total_capacity > 0)) return -1;
    return Math.min(100, Math.max(0, p));
}

// Nível do contrato; ausente, obsoleto ou sem dado = "" (cor neutra)
function windowLevel(acc, win, pct) {
    if (pct < 0 || acc.stale === true || acc.no_data === true) return "";
    var l = win.alert_level;
    return (l === "normal" || l === "warning" || l === "critical") ? l : "";
}

function windowElapsed(acc, win, pct) {
    if (pct < 0 || acc.stale === true || !(win.window_seconds > 0) || !isNum(win.elapsed_fraction)) return -1;
    return Math.min(1, Math.max(0, win.elapsed_fraction));
}

function levelWord(level, tr) {
    if (level === "critical") return tr("crítico");
    if (level === "warning") return tr("atenção");
    if (level === "normal") return tr("normal");
    return tr("sem nível");
}

function pctWord(pct) { return pct < 0 ? "-" : Math.round(pct) + "%"; }

// Atualizações (ticket 39): texto do status.json é não confiável, então só versão curta e URL da release do widget
var RELEASE_URL = /^https:\/\/github\.com\/victorlcs87\/plasma-ai-usage-widget\/[A-Za-z0-9._~\/%+-]{0,200}$/;
var CLI_NAMES = { claude: "Claude Code", codex: "Codex", gemini: "Gemini CLI" };

// Item com nova versão disponível, ou null
function updateItem(statusData, key) {
    var u = statusData && statusData.updates;
    var it = u && u.items && u.items[key];
    if (!it || it.available !== true || typeof it.latest !== "string" || it.latest.length > 64) return null;
    return {
        latest: it.latest,
        url: (typeof it.url === "string" && RELEASE_URL.test(it.url)) ? it.url : ""
    };
}

// {widget, clis, lines}: lines = textos do popup (url só no widget)
function updateSummary(statusData, tr) {
    var widget = updateItem(statusData, "widget");
    var clis = [], lines = [];
    if (widget) lines.push({ text: tr("Nova versão do widget: %1", widget.latest), url: widget.url });
    ["claude", "codex", "gemini"].forEach(function (k) {
        var it = updateItem(statusData, k);
        if (!it) return;
        clis.push(k);
        lines.push({ text: tr("Nova versão do %1: %2", CLI_NAMES[k], it.latest), url: "" });
    });
    return { widget: widget, clis: clis, lines: lines };
}

function buildModel(statusData, cfg, tr) {
    var agents = (statusData && statusData.agents) || {};
    return visibleProviders(cfg).map(function (key) {
        var info = Presets.providerInfo(key);
        var ag = agents[key];
        var acc = activeAccount(ag);
        var m = {
            provider: key, name: (ag && ag.name) || info.name, letter: info.letter,
            innerPct: -1, outerPct: -1, innerLevel: "", outerLevel: "", innerElapsed: -1, outerElapsed: -1,
            health: "", update: updateItem(statusData, key)
        };
        if (!acc) {
            var hasAccounts = ag && ag.accounts && ag.accounts.length > 0;
            m.description = hasAccounts ? tr("sem conta ativa no sistema") : tr("sem dados");
            return m;
        }
        var nw = acc.native_window, ww = acc.weekly_window;
        m.innerPct = windowPct(acc, nw, "release_time");
        m.outerPct = windowPct(acc, ww, "cycle_reset_time");
        m.innerLevel = windowLevel(acc, nw, m.innerPct);
        m.outerLevel = windowLevel(acc, ww, m.outerPct);
        m.innerElapsed = windowElapsed(acc, nw, m.innerPct);
        m.outerElapsed = windowElapsed(acc, ww, m.outerPct);
        var st = acc.health ? acc.health.status : "";
        m.health = (st && st !== "valid") ? st : "";
        var tail = acc.stale === true ? tr("dados desatualizados") : "";
        if (acc.limit_changes && acc.limit_changes.length > 0) tail += (tail ? ", " : "") + tr("limites mudaram");
        if (m.update) tail += (tail ? ", " : "") + tr("nova versão %1", m.update.latest);
        m.description = tr("Janela nativa %1 (%2)", pctWord(m.innerPct), levelWord(m.innerLevel, tr))
            + ", " + tr("semanal %1 (%2)", pctWord(m.outerPct), levelWord(m.outerLevel, tr))
            + (tail ? ", " + tail : "");
        return m;
    });
}

// Pior saúde entre as Contas Ativas visíveis ("" = tudo válido ou sem dados)
function worstHealth(model) {
    var worst = "";
    model.forEach(function (m) {
        if (m.health && (m.health === "session_expired" || worst === "")) worst = m.health;
    });
    return worst;
}

// Tempo restante legível ("2h 15min"); vencido (<= 0) = "já liberado"
function formatRemaining(ms, tr) {
    if (ms <= 0) return tr("já liberado");
    var min = Math.floor(ms / 60000);
    if (min < 1) return tr("menos de 1 min");
    if (min < 60) return min + "min";
    var h = Math.floor(min / 60);
    if (h < 24) return h + "h " + (min % 60) + "min";
    return Math.floor(h / 24) + "d " + (h % 24) + "h";
}

// Uma linha por janela: "Janela nativa: 40% — libera em 2h 15min"; sem dado = "—", nunca 0%
function windowLine(acc, win, resetKey, label, now, tr) {
    var pct = windowPct(acc, win, resetKey);
    if (pct < 0) return label + ": —";
    var reset = parseIso(win[resetKey]);
    if (!isNaN(reset) && reset <= now) return label + ": " + formatRemaining(0, tr);  // sem % antigo ambíguo
    var line = label + ": " + Math.round(pct) + "%";
    if (!isNaN(reset)) line += " — " + tr("libera em %1", formatRemaining(reset - now, tr));
    return line;
}

// Texto da dica (texto puro): todos os limites dos provedores visíveis, Conta Ativa no Sistema
function tooltipText(statusData, cfg, tr, now) {
    var agents = (statusData && statusData.agents) || {};
    var blocks = visibleProviders(cfg).map(function (key) {
        var ag = agents[key];
        var name = (ag && ag.name) || Presets.providerInfo(key).name;
        var acc = activeAccount(ag);
        if (!acc) return name + ": " + tr("sem conta ativa no sistema");
        var notes = [], st = acc.health ? acc.health.status : "";
        if (st === "session_expired") notes.push(tr("Sessão expirada"));
        else if (st === "not_configured") notes.push(tr("Conta não configurada"));
        else if (st && st !== "valid") notes.push(tr("Erro na conta"));
        if (acc.stale === true) notes.push(tr("dados desatualizados"));
        if (acc.limit_changes && acc.limit_changes.length > 0) notes.push(tr("limites mudaram"));
        return name + "\n  " + windowLine(acc, acc.native_window, "release_time", tr("Janela nativa"), now, tr)
            + "\n  " + windowLine(acc, acc.weekly_window, "cycle_reset_time", tr("Semanal"), now, tr)
            + (notes.length ? "\n  " + notes.join(", ") : "");
    });
    return blocks.join("\n");
}
