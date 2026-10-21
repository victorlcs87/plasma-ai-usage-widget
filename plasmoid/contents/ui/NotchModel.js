.pragma library
.import "Presets.js" as Presets
.import "ViewPrefs.js" as ViewPrefs

// Modelo do Notch compacto: função pura sobre status.json + config (testável sem Plasma).
// `tr` = safeI18n do chamador.

function visibleProviders(cfg) {
    var hidden = String(cfg.hiddenProviders || "").split(",");
    return Presets.normalizeOrder(cfg.providerOrder).filter(function (k) { return hidden.indexOf(k) === -1; });
}

// Ocultar sem o processo da CLI (ticket 37): "off" (padrão) | "widget" | "provider", vindo do contrato
var RUNNING_MAX_AGE_MS = 180000;
var RUNNING_FUTURE_SKEW_MS = 30000;

function hideMode(statusData) {
    var v = statusData && statusData.visibility;
    var m = v && v.hide_when_not_running;
    return (m === "widget" || m === "provider") ? m : "off";
}

// Só `running === false` explícito e leitura recente (null, ausente, antigo, no futuro ou data inválida =
// não esconde). `nowMs` vem do chamador (relógio observável, atualizado por um Timer), nunca de Date.now().
function notRunning(statusData, key, nowMs) {
    var checked = Date.parse(statusData && statusData.running_checked_at);
    var age = nowMs - checked;
    if (isNaN(age) || age < -RUNNING_FUTURE_SKEW_MS || age > RUNNING_MAX_AGE_MS) return false;
    var ag = statusData.agents && statusData.agents[key];
    return !!ag && ag.running === false;
}

// Modo "provider": provedores visíveis sem processo agora (o chamador pode confirmá-los com atraso)
function idleProviders(statusData, cfg, nowMs) {
    if (hideMode(statusData) !== "provider") return [];
    return visibleProviders(cfg).filter(function (k) { return notRunning(statusData, k, nowMs); });
}

// Modo "widget": todos os provedores visíveis sem processo (com ao menos um visível)
function widgetIdle(statusData, cfg, nowMs) {
    if (hideMode(statusData) !== "widget") return false;
    var keys = visibleProviders(cfg);
    return keys.length > 0 && keys.every(function (k) { return notRunning(statusData, k, nowMs); });
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

// Usado (padrão) ou restante (preferência do usuário); desconhecido = "-"
function pctWord(pct, remaining, tr) {
    return pct < 0 ? "-" : ViewPrefs.shownPct(pct, remaining) + "%" + (remaining ? " " + (tr ? tr("restante") : "restante") : "");
}

// Estado da Sessão (busy/waiting/idle) da Conta Ativa (Claude ou Codex): o overlay ao vivo
// (cfg.sessionOverlay, chave "provedor/id da Conta") vence o campo do contrato; desligado ou
// desconhecido = "" (sem indicador)
function sessionState(provider, acc, cfg) {
    if (!cfg.showSession) return "";
    var s = (cfg.sessionOverlay && cfg.sessionOverlay[provider + "/" + acc.id]) || acc.session_state;
    return (s === "busy" || s === "waiting" || s === "idle") ? s : "";
}

function sessionWord(state, tr) {
    if (state === "busy") return tr("sessão ocupada");
    if (state === "waiting") return tr("aguardando você");
    if (state === "idle") return tr("sessão ociosa");
    return "";
}

// Atualizações (ticket 39): texto do status.json é não confiável, então só versão curta e URL da release do widget
var RELEASE_URL = /^https:\/\/github\.com\/victorlcs87\/plasma-ai-usage-widget\/releases\/(?:[A-Za-z0-9._~\/+-]|%[0-9A-Fa-f]{2}){0,200}$/;
var URL_FORBIDDEN = /\.\.|%2e|%2f|%5c/i;  // igual ao coletor (updates.py)
function validReleaseUrl(u) { return typeof u === "string" && RELEASE_URL.test(u) && !URL_FORBIDDEN.test(u); }
var CLI_NAMES = { claude: "Claude Code", codex: "Codex", gemini: "Gemini CLI" };

// Item com nova versão disponível, ou null
function updateItem(statusData, key) {
    var u = statusData && statusData.updates;
    var it = u && u.items && u.items[key];
    if (!it || it.available !== true || typeof it.latest !== "string" || it.latest.length > 64) return null;
    return {
        latest: it.latest,
        url: validReleaseUrl(it.url) ? it.url : ""
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

function buildModel(statusData, cfg, tr, nowMs) {
    var agents = (statusData && statusData.agents) || {};
    // cfg.idleProviders (já confirmados com atraso pelo chamador) tem precedência sobre a leitura direta
    var idle = Array.isArray(cfg.idleProviders) ? cfg.idleProviders : idleProviders(statusData, cfg, nowMs);
    return visibleProviders(cfg).filter(function (k) {
        return idle.indexOf(k) === -1;
    }).map(function (key) {
        var info = Presets.providerInfo(key);
        var ag = agents[key];
        var acc = activeAccount(ag);
        var m = {
            provider: key, name: (ag && ag.name) || info.name, letter: info.letter,
            innerPct: -1, outerPct: -1, innerLevel: "", outerLevel: "", innerElapsed: -1, outerElapsed: -1,
            health: "", sessionState: "", update: updateItem(statusData, key)
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
        m.sessionState = sessionState(key, acc, cfg);
        var tail = acc.stale === true ? tr("dados desatualizados") : "";
        if (acc.limit_changes && acc.limit_changes.length > 0) tail += (tail ? ", " : "") + tr("limites mudaram");
        if (m.sessionState) tail += (tail ? ", " : "") + sessionWord(m.sessionState, tr);
        if (m.update) tail += (tail ? ", " : "") + tr("nova versão %1", m.update.latest);
        m.description = tr("Janela nativa %1 (%2)", pctWord(m.innerPct, cfg.remaining, tr), levelWord(m.innerLevel, tr))
            + ", " + tr("semanal %1 (%2)", pctWord(m.outerPct, cfg.remaining, tr), levelWord(m.outerLevel, tr))
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
function windowLine(acc, win, resetKey, label, now, tr, cfg) {
    cfg = cfg || {};
    var pct = windowPct(acc, win, resetKey);
    if (pct < 0) return label + ": —";
    var reset = parseIso(win[resetKey]);
    if (!isNaN(reset) && reset <= now) return label + ": " + formatRemaining(0, tr);  // sem % antigo ambíguo
    var line = label + ": " + pctWord(pct, cfg.remaining, tr);
    if (!isNaN(reset)) line += " — " + (cfg.date ? tr("libera %1", ViewPrefs.dateText(reset, now)) : tr("libera em %1", formatRemaining(reset - now, tr)));
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
        return name + "\n  " + windowLine(acc, acc.native_window, "release_time", tr("Janela nativa"), now, tr, cfg)
            + "\n  " + windowLine(acc, acc.weekly_window, "cycle_reset_time", tr("Semanal"), now, tr, cfg)
            + (notes.length ? "\n  " + notes.join(", ") : "");
    });
    return blocks.join("\n");
}

// ---- Popup (ticket 33) ----

// Há conteúdo em usage_details? (objeto vazio ou listas vazias não abrem "Histórico e detalhes")
function hasUsageDetails(d) {
    if (!d) return false;
    return ["tokens_by_model", "tokens_by_project", "quota_by_model"].some(function (k) { return d[k] && d[k].length > 0; })
        || !!d.extra_usage || !!d.credits || !!d.current_model;
}

// Provedores do popup na ordem/visibilidade escolhidas; cada um com suas Contas (a Ativa no Sistema primeiro).
// Só os provedores conhecidos (Presets.providers) aparecem, como no painel e no coletor: um provedor
// desconhecido no status.json é ignorado de propósito (novos provedores estão fora do escopo da spec 05).
function popupProviders(statusData, prefs) {
    var agents = (statusData && statusData.agents) || {};
    return prefs.order.map(function (key) {
        var info = Presets.providerInfo(key), ag = agents[key];
        var accs = ((ag && ag.accounts) || []).map(function (a) {
            if (!a.provider) a.provider = key;
            return a;
        });
        var active = activeAccount(ag);
        if (active) accs = [active].concat(accs.filter(function (a) { return a !== active; }));
        return { key: key, name: (ag && ag.name) || info.name, letter: info.letter, accounts: accs, hasActive: !!active };
    });
}

function windowTitle(kind, win, tr) {
    if (kind === "weekly") return tr("Janela Semanal (7 dias)");
    var t = (win && win.type) || "";
    return t === "5h" ? tr("Janela Ativa (5h)") : t === "daily" ? tr("Janela Diária") : t ? tr("Janela Ativa (%1)", t) : tr("Janela Ativa");
}

// Previsão de Esgotamento: vazia sem previsão confiável (obsoleto, sem dado); `warn` = esgota antes da liberação
function forecast(acc, win, nowMs, tr) {
    var fc = win && win.forecast;
    if (!fc || acc.stale === true || acc.no_data === true) return { text: "", warn: false };
    if (!fc.exhausts_at) return { text: tr("Sem esgotamento previsto"), warn: false };
    var at = parseIso(fc.exhausts_at);
    if (isNaN(at)) return { text: "", warn: false };
    var sec = Math.max(0, Math.round((at - nowMs) / 1000));
    var when = sec <= 0 ? tr("agora")
        : sec >= 86400 ? tr("%1d %2h", Math.floor(sec / 86400), Math.floor((sec % 86400) / 3600))
        : sec >= 3600 ? tr("%1h %2min", Math.floor(sec / 3600), Math.floor((sec % 3600) / 60))
        : tr("%1 min", Math.max(1, Math.round(sec / 60)));
    var text = sec > 0 ? tr("Esgota em %1 (%2)", when, ViewPrefs.dateText(at, nowMs).slice(-5)) : tr("Esgota %1", when);
    return { text: fc.before_release ? text : tr("%1, após a liberação", text), warn: fc.before_release === true };
}

// Tudo que o popup mostra de uma janela. `prefs` = ViewPrefs.config; sem dado: "—", esmaecido, sem nível/previsão
function windowView(acc, win, kind, prefs, nowMs, tr) {
    var key = kind === "weekly" ? "cycle_reset_time" : "release_time";
    var pct = windowPct(acc, win, key), stale = acc.stale === true;
    var v = { title: windowTitle(kind, win, tr), known: pct >= 0, pct: pct, text: ViewPrefs.pctText(pct, prefs.remaining),
              level: windowLevel(acc, win, pct), elapsed: windowElapsed(acc, win, pct), dim: pct < 0 || stale || acc.no_data === true,
              reset: "", resetFull: "", tokens: "", forecast: { text: "", warn: false } };
    var resetMs = win ? parseIso(win[key] || win.resets_at) : NaN;
    if (v.elapsed >= 0 && !isNaN(resetMs))  // marca de tempo decorrido ao vivo, em passos de 0,5%
        v.elapsed = Math.round(Math.min(1, Math.max(0, 1 - (resetMs - nowMs) / (win.window_seconds * 1000))) * 200) / 200;
    if (pct < 0) v.reset = v.resetFull = tr("Sem dados");
    else if (stale) v.reset = v.resetFull = tr("Dados desatualizados") + (isNaN(resetMs) ? "" : " · " + tr("liberação prevista %1", ViewPrefs.dateText(resetMs, nowMs)));
    else if (!isNaN(resetMs)) {
        var sec = Math.floor((resetMs - nowMs) / 1000);
        if (sec <= 0) v.reset = v.resetFull = tr("Cota liberada");
        else {
            var cd = ViewPrefs.countdown(sec), dt = ViewPrefs.dateText(resetMs, nowMs);
            v.reset = prefs.date ? tr("libera %1", dt) : tr("libera em %1", cd);
            v.resetFull = tr("libera em %1 (%2)", cd, dt);
        }
    }
    if (pct >= 0 && win.tokens_used > 0) v.tokens = tr("%1 tokens", win.tokens_used.toLocaleString());
    if (pct >= 0) v.forecast = forecast(acc, win, nowMs, tr);
    return v;
}

// Texto único para tecnologias assistivas (a informação nunca depende só da cor)
function viewSummary(v, remaining, tr) {
    var s = v.title + ": " + (v.known ? v.text + " " + (remaining ? tr("restante") : tr("usado")) : tr("sem dados"));
    if (v.level) s += ", " + levelWord(v.level, tr);
    if (v.resetFull) s += ", " + v.resetFull;
    return s + (v.forecast.text ? ", " + v.forecast.text : "");
}
