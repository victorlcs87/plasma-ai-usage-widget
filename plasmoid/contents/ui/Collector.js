.pragma library

// Única implementação dos comandos que o widget dispara no shell (main, popup e configuração).
// Ordem de resolução: PATH, ~/.local/bin, pipx e, só por último, o caminho configurado (opção collectorPath,
// vazia por padrão; aceita ~/); sem nada disso, `python3 -m ai_usage_collector`.
function shellQuote(str) {
    if (str === null || str === undefined) return "''";
    return "'" + String(str).replace(/'/g, "'\\''") + "'";
}

var PIPX = "$HOME/.local/share/pipx/venvs/plasma-ai-usage-collector/bin/";

// Um degrau da escada: usa `path` se existir e for executável
function _step(path, run) { return "elif [ -x \"" + path + "\" ]; then " + run + "; "; }

// quotedArgs: argumentos já passados por shellQuote. O caminho configurado vai como $1 (nunca interpolado no script).
function buildCollectorCommand(quotedArgs, collectorPath) {
    var bin = "ai-usage-collector";
    return "bash -c 'c=${1/#\\~/$HOME}; shift; if command -v " + bin + " >/dev/null 2>&1; then " + bin + " \"$@\"; " +
           _step("$HOME/.local/bin/" + bin, "\"$HOME/.local/bin/" + bin + "\" \"$@\"") +
           _step(PIPX + bin, "\"" + PIPX + bin + "\" \"$@\"") +
           "elif [ -n \"$c\" ] && [ -x \"$c\" ]; then \"$c\" \"$@\"; " +
           "else python3 -m ai_usage_collector \"$@\"; fi' _ " + shellQuote(collectorPath || "") + " " + (quotedArgs || "");
}

// Caminho leve do Estado da Sessão: não importa o coletor inteiro (~60 ms contra ~240 ms)
function buildSessionCommand(collectorPath) {
    var s = "ai-usage-session-state", bin = "ai-usage-collector";
    return "bash -c 'c=${1/#\\~/$HOME}; if command -v " + s + " >/dev/null 2>&1; then " + s + "; " +
           _step("$HOME/.local/bin/" + s, "\"$HOME/.local/bin/" + s + "\"") +
           _step(PIPX + s, "\"" + PIPX + s + "\"") +
           "elif command -v " + bin + " >/dev/null 2>&1; then " + bin + " --session-state; " +  // instalação antiga, sem o caminho leve
           _step("$HOME/.local/bin/" + bin, "\"$HOME/.local/bin/" + bin + "\" --session-state") +
           _step(PIPX + bin, "\"" + PIPX + bin + "\" --session-state") +
           "elif [ -n \"$c\" ] && [ -x \"$(dirname \"$c\")/" + s + "\" ]; then \"$(dirname \"$c\")/" + s + "\"; " +
           "elif [ -n \"$c\" ] && [ -x \"$c\" ]; then \"$c\" --session-state; " +
           "else python3 -m ai_usage_collector --session-state; fi' _ " + shellQuote(collectorPath || "");
}

// Estado do Instalador do Coletor (ticket 49): `collector-installer.py status` imprime uma linha JSON (ADR-0012).
// Só mostra e valida; nada aqui instala. O script roda com o python3 do sistema; sem ele o shell devolve 127.
var COLLECTOR_STATES = ["ausente", "desatualizado", "ok", "mais_novo", "python_indisponivel"];

// scriptUrl: Qt.resolvedUrl(...) do script empacotado (funciona instalado e em diretório com espaço/acento)
function scriptPath(scriptUrl) { return decodeURIComponent(String(scriptUrl).replace(/^file:\/\//, "")); }

function buildStatusCommand(scriptFile, required, collectorPath) {
    return "python3 " + shellQuote(scriptFile) + " status --required " + shellQuote(required) +
           " --collector-path " + shellQuote(collectorPath || "");
}

// Saída do status -> {state, installed, required, message} ou null (vazia, inválida ou estado desconhecido: sem card)
function parseStatus(stdout, exitCode) {
    if (exitCode === 127) return { state: "python_indisponivel", installed: "", required: "", message: "" };
    var o;
    try { o = JSON.parse(stdout); } catch (e) { return null; }
    if (!o || typeof o !== "object" || COLLECTOR_STATES.indexOf(o.state) < 0) return null;
    var str = function (v) { return v === null || v === undefined ? "" : String(v); };
    return { state: o.state, installed: str(o.installed), required: str(o.required), message: str(o.message) };
}

// Precisa de ação do usuário (marcador no painel/Notch); `mais_novo` é só aviso no popup
function needsAttention(st) {
    return !!st && (st.state === "ausente" || st.state === "desatualizado" || st.state === "python_indisponivel");
}

// ---- Instalação pelo widget (ticket 50, ADR-0012): só roda depois da confirmação do usuário ----
// A versão vai ao shell: só X.Y.Z estrito (nunca URL, índice ou texto livre); inválida => "" e nada é executado.
function isVersion(v) { return /^[0-9]+\.[0-9]+\.[0-9]+$/.test(String(v === null || v === undefined ? "" : v)); }

function buildInstallCommand(scriptFile, version) {
    if (!isVersion(version)) return "";
    return "python3 " + shellQuote(scriptFile) + " install --version " + shellQuote(version);
}

var INSTALL_CAUSES = ["python_indisponivel", "rede", "versao_inexistente", "permissao", "conflito_em_local_bin", "verificacao", "sem_hash", "kpackagetool", "falha"];
var INSTALL_STEPS = ["venv", "download", "install", "link", "verify", "plasmoid_hash", "plasmoid_download", "plasmoid_verify", "plasmoid_install"];

// Linhas JSON do `install` -> {steps: [{step, status, message}], result: objeto final ou null}. Linhas inválidas são ignoradas.
function _installLines(stdout) {
    var steps = [], result = null, lines = String(stdout || "").split("\n");
    for (var i = 0; i < lines.length; i++) {
        var o;
        try { o = JSON.parse(lines[i]); } catch (e) { continue; }
        if (!o || typeof o !== "object") continue;
        if (typeof o.result === "string") result = o;
        else if (INSTALL_STEPS.indexOf(o.step) >= 0) steps.push({ step: o.step, status: String(o.status || ""), message: String(o.message || "") });
    }
    return { steps: steps, result: result };
}

// Passo em andamento (último "start" sem "ok"/"error" depois) ou "" — para o progresso quando a saída chega parcial
function currentStep(stdout) {
    var st = _installLines(stdout).steps;
    return st.length && st[st.length - 1].status === "start" ? st[st.length - 1].step : "";
}

// Saída completa do `install` -> {ok, cause, message, log: [texto], failedStep}. Sucesso só com exit 0 E linha final result=ok.
function parseInstall(stdout, exitCode) {
    var p = _installLines(stdout), r = p.result, failed = "";
    for (var i = 0; i < p.steps.length; i++) if (p.steps[i].status === "error") failed = p.steps[i].step;
    if (exitCode === 0 && r && r.result === "ok") return { ok: true, cause: "", message: String(r.message || "").slice(0, 500), log: [], failedStep: "" };
    var cause = exitCode === 127 ? "python_indisponivel" : (r && INSTALL_CAUSES.indexOf(r.cause) >= 0 ? r.cause : "falha");
    var log = (r && Array.isArray(r.log) ? r.log : []).slice(-30).map(function (l) { return String(l).slice(0, 300); });
    return { ok: false, cause: cause, message: r ? String(r.message || "").slice(0, 500) : "", log: log, failedStep: failed };
}

// ---- Atualização do Widget (ticket 77, ADR-0014): Coletor + .plasmoid, só depois da confirmação do usuário ----
// `update` emite as mesmas linhas JSON do `install` (mais os passos plasmoid_*), então o parser é o mesmo.
function buildUpdateCommand(scriptFile, version) {
    if (!isVersion(version)) return "";
    return "python3 " + shellQuote(scriptFile) + " update --version " + shellQuote(version);
}
var parseUpdate = parseInstall;

// Máquina de estados da atualização (pura, testada sem o plasmashell). cur = estado atual do widgetUpdate.
// Mescla `extra` sobre o novo estado; result e version persistem, step zera.
function nextWidgetUpdate(cur, state, extra) {
    var o = { state: state, result: cur.result || "", version: cur.version || "", step: "" };
    for (var k in extra) o[k] = extra[k];
    return o;
}
// Dados do DataSource da atualização -> {done, next}. Parcial (sem "exit code") só avança o passo e mantém `to`;
// completo vira concluido (to preservado) ou erro com a causa classificada.
function widgetUpdateOnData(cur, stdout, exitCode) {
    var out = String(stdout || "");
    if (exitCode === undefined) return { done: false, next: nextWidgetUpdate(cur, "atualizando", { to: cur.to, step: currentStep(out) }) };
    var r = parseUpdate(out, exitCode);
    if (r.ok) return { done: true, next: nextWidgetUpdate(cur, "concluido", { to: cur.to }) };
    return { done: true, next: nextWidgetUpdate(cur, "erro", { cause: r.cause, message: r.message, log: r.log, failedStep: r.failedStep }) };
}
// Watchdog: busca ou atualização presa vira erro "falha"; fora desses estados não há nada preso (null)
function widgetUpdateStuck(cur) {
    if (cur.state !== "buscando" && cur.state !== "atualizando") return null;
    return nextWidgetUpdate(cur, "erro", { cause: "falha", message: "", log: [], failedStep: "" });
}

// "v1.2.5" / "1.2.5" -> "1.2.5"; qualquer outra coisa -> "" (a versão vai ao shell)
function cleanVersion(v) {
    var s = String(v === null || v === undefined ? "" : v).replace(/^v/, "");
    return isVersion(s) ? s : "";
}

// Saída do `ai-usage-collector --check-update` (uma linha JSON) -> {update: nova|atual|indisponivel|desligada, version}.
// Qualquer saída vazia, inválida ou desconhecida vira "indisponivel"; "nova" sem versão X.Y.Z também.
function parseCheckUpdate(stdout) {
    var o, bad = { update: "indisponivel", version: "" };
    try { o = JSON.parse(String(stdout || "").trim().split("\n").pop()); } catch (e) { return bad; }
    if (!o || typeof o !== "object") return bad;
    if (o.update === "desligada") return { update: "desligada", version: "" };
    if (o.update === "atual") return { update: "atual", version: cleanVersion(o.version) };
    if (o.update === "nova" && cleanVersion(o.version) !== "") return { update: "nova", version: cleanVersion(o.version) };
    return bad;
}

// Recarga do widget: só roda no clique do usuário (nunca automática); desacoplada para sobreviver ao fim do plasmashell
function reloadCommand() { return "setsid -f plasmashell --replace >/dev/null 2>&1"; }
