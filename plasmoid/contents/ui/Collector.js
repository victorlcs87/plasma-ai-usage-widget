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
