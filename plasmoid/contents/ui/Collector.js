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
