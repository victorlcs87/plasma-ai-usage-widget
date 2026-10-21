"""Instala e remove os hooks do Estado da Sessao no settings.json do Claude Code (ADR-0009).

So age quando o usuario pede (--install-hooks / --uninstall-hooks). Os hooks do widget sao
reconhecidos pelo marcador no fim do comando; tudo o mais no arquivo e preservado.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from ai_usage_collector import session_state

MARKER = "# plasma-ai-usage:session-hook"
# PostToolUse alem dos tres eventos do ticket: sem ele, aprovar uma permissao deixaria o estado
# "aguardando" ate o Stop; tambem serve de batimento para sessoes longas.
EVENTS = {"UserPromptSubmit": "busy", "PostToolUse": "busy", "Stop": "idle", "Notification": "waiting"}
HOOK_TIMEOUT = 5
BACKUP_SUFFIX = ".plasma-ai-usage.bak"
_LOCK_WAIT_SECONDS = 5


class HooksError(Exception):
    """Falha que deixa o settings.json intacto."""


def hook_command(state: str, state_dir: Path) -> str:
    """Comando executado pelo shell do Claude Code: caminhos absolutos entre aspas, sem dados
    externos; `|| true` garante exit 0 mesmo se o Python sumir (um hook nunca quebra o Claude).
    """
    script = Path(session_state.__file__).resolve()
    return (
        f"{shlex.quote(sys.executable)} -I {shlex.quote(str(script))} {state} {shlex.quote(str(state_dir))}"
        f" >/dev/null 2>&1 || true {MARKER}"
    )


def is_ours(hook: Any) -> bool:
    cmd = hook.get("command") if isinstance(hook, dict) else None
    return isinstance(cmd, str) and cmd.endswith(" " + MARKER)


def _our_hooks(groups: list[Any]) -> list[tuple[list[Any], int]]:
    """(lista de hooks, indice) de cada hook nosso nos grupos de um evento."""
    return [
        (g["hooks"], i)
        for g in groups if isinstance(g, dict) and isinstance(g.get("hooks"), list)
        for i, h in enumerate(g["hooks"]) if is_ours(h)
    ]


def _hooks_section(data: dict[str, Any], create: bool) -> dict[str, Any] | None:
    hooks = data.get("hooks")
    if hooks is None:
        if not create:
            return None
        hooks = data["hooks"] = {}
    if not isinstance(hooks, dict):
        raise HooksError('"hooks" no settings.json não é um objeto; nada foi alterado.')
    return hooks


def add_hooks(data: dict[str, Any], state_dir: Path) -> bool:
    """Garante exatamente um hook nosso por evento, no lugar se ja existir. True se mudou algo."""
    hooks = _hooks_section(data, create=True)
    changed = False
    for event, state in EVENTS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise HooksError(f'"hooks.{event}" no settings.json não é uma lista; nada foi alterado.')
        desired = {"type": "command", "command": hook_command(state, state_dir), "timeout": HOOK_TIMEOUT}
        ours = _our_hooks(groups)
        if not ours:
            groups.append({"hooks": [desired]})
            changed = True
            continue
        if ours[0][0][ours[0][1]] != desired:
            ours[0][0][ours[0][1]] = desired
            changed = True
        for lst, i in sorted(ours[1:], key=lambda t: t[1], reverse=True):  # duplicatas nossas
            del lst[i]
            changed = True
    return changed


def remove_hooks(data: dict[str, Any]) -> bool:
    """Remove so os hooks nossos e os contenedores que ficaram vazios por causa disso."""
    hooks = _hooks_section(data, create=False)
    if hooks is None:
        return False
    changed = False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list) or not _our_hooks(groups):
            continue
        changed = True
        kept = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list) and any(is_ours(h) for h in g["hooks"]):
                g["hooks"] = [h for h in g["hooks"] if not is_ours(h)]
                if not g["hooks"]:
                    continue  # grupo que so existia por causa do nosso hook
            kept.append(g)
        hooks[event] = kept
        if not hooks[event]:
            del hooks[event]
    if changed and not hooks:
        del data["hooks"]
    return changed


def _lock(directory: Path) -> int:
    """flock no proprio diretorio (sem arquivo residual), com espera limitada."""
    fd = os.open(directory, os.O_RDONLY)
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() > deadline:
                os.close(fd)
                raise HooksError("Outro processo está alterando o settings.json; tente de novo.")
            time.sleep(0.05)


def _backup(real: Path, raw: bytes) -> Path:
    """Copia 0600 do arquivo original, criada uma unica vez (antes da 1a alteracao)."""
    bak = real.with_name(real.name + BACKUP_SUFFIX)
    try:
        fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return bak
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return bak


def _parse(raw: bytes, real: Path) -> tuple[dict[str, Any], str, bool]:
    """(dados, indentacao, termina com newline). Arquivo invalido: backup e aborta sem alterar."""
    try:
        text = raw.decode("utf-8")
        data = json.loads(text) if text.strip() else {}
    except ValueError as e:  # inclui UnicodeDecodeError e JSONDecodeError
        bak = _backup(real, raw)
        raise HooksError(f"{real} não é um JSON válido ({e}); nada foi alterado. Backup em {bak}.")
    if not isinstance(data, dict):
        raise HooksError(f"{real} não contém um objeto JSON; nada foi alterado.")
    m = re.search(r'^([ \t]+)"', text, re.M)
    return data, (m.group(1) if m else "  "), (text.endswith("\n") if text.strip() else True)


def _edit(settings: Path, mutate: Callable[[dict[str, Any]], bool], creates: bool) -> bool:
    """Le, altera e regrava o settings.json de forma atomica; True se o arquivo mudou."""
    real = Path(os.path.realpath(settings))  # symlink (dotfiles): o alvo e substituido, o link fica
    if not real.exists() and not creates:
        return False
    real.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    dirfd = _lock(real.parent)
    try:
        raw = real.read_bytes() if real.exists() else b""
        data, indent, newline = _parse(raw, real)
        if not mutate(data):
            return False
        mode = (real.stat().st_mode & 0o7777) if real.exists() else 0o600
        if raw:
            _backup(real, raw)
        fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=f".{real.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=indent, ensure_ascii=False) + ("\n" if newline else ""))
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, mode)
            # O Claude Code nao usa o nosso lock: se ele regravou o arquivo, aborta em vez de sobrescrever.
            if (real.read_bytes() if real.exists() else b"") != raw:
                raise HooksError(f"{real} foi alterado por outro processo; nada foi gravado. Tente de novo.")
            os.replace(tmp, real)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return True
    finally:
        os.close(dirfd)  # solta o flock


def settings_path() -> Path:
    return session_state.claude_config_dir() / "settings.json"


def install_hooks(state_dir: Path, settings: Path | None = None) -> str:
    settings = settings or settings_path()
    changed = _edit(settings, lambda d: add_hooks(d, state_dir), creates=True)
    verb = "instalados" if changed else "já estavam instalados"
    return f"Hooks do Estado da Sessão {verb} em {settings}."


def uninstall_hooks(settings: Path | None = None) -> str:
    settings = settings or settings_path()
    changed = _edit(settings, remove_hooks, creates=False)
    return f"Hooks do Estado da Sessão removidos de {settings}." if changed else f"Nenhum hook do widget em {settings}."
