"""Estado da Sessao do Claude Code (ADR-0009): o hook grava, o coletor le.

Este modulo roda como script isolado (`python -I session_state.py <estado> <dir>`) dentro do
hook do Claude Code: so pode importar a biblioteca padrao e precisa ser rapido. O hook nunca
falha o Claude Code (exit 0, sem stdout) e nunca grava o conteudo do prompt: do JSON recebido
na entrada padrao so usa `session_id` (gravado como hash) e `notification_type`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

STATES = ("busy", "waiting", "idle")
STATE_DIRNAME = "session-state"
# Sem Stop uma sessao interrompida (Esc, terminal fechado) nao pode ficar "ocupada" para sempre:
# o estado expira. Ocupada/aguardando expiram rapido (o PostToolUse serve de batimento); limitacao:
# uma unica ferramenta que rode mais que isso sem nenhum evento deixa de contar como ocupada.
TTL_SECONDS = {"busy": 300, "waiting": 300, "idle": 1800}
# Tipos de Notification que de fato esperam o usuario. Nomes conforme a documentacao do Claude Code;
# NAO foram verificados neste repositorio: ajuste aqui. Tipo ausente ou desconhecido = nao grava.
WAITING_NOTIFICATION_TYPES = ("permission_prompt", "elicitation_dialog")
_PURGE_SECONDS = 86400
_TMP_PURGE_SECONDS = 60
_MAX_STDIN = 1 << 20  # prefixo analisado como JSON; o resto da entrada e lido e descartado
_DRAIN_MAX_BYTES = 256 << 20
_DRAIN_MAX_SECONDS = 2.0
_HEAD = 4096  # session_id e notification_type vem no inicio do JSON do Claude Code
_SID_RE = re.compile(rb'"session_id"\s*:\s*"([A-Za-z0-9_-]{1,128})"')
_NTYPE_RE = re.compile(rb'"notification_type"\s*:\s*"([a-z_]{1,64})"')
ACCOUNTS_FILENAME = "session-accounts.json"
_FUTURE_SKEW = 300  # relogio adiantado alem disso invalida o registro


def state_dir_for(cache_path: str | Path) -> Path:
    """Os estados ficam em um diretorio ao lado do status.json."""
    return Path(cache_path).expanduser().resolve().parent / STATE_DIRNAME


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser().resolve()


def write_event(state_dir: str | Path, state: str, session_id: str, now: float | None = None) -> None:
    """Grava atomicamente (0600) o estado de uma sessao; descarta registros muito antigos."""
    if state not in STATES:
        raise ValueError(state)
    now = time.time() if now is None else now
    d = Path(state_dir)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)  # diretorio ja existente com permissao frouxa
    name = hashlib.sha256(session_id.encode("utf-8", "replace")).hexdigest()[:16]
    record = {"state": state, "ts": now, "config_dir": str(claude_config_dir())}
    tmp = d / f".{name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f)
        os.replace(tmp, d / f"{name}.json")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    for old in d.iterdir():
        try:
            limit = _TMP_PURGE_SECONDS if old.suffix == ".tmp" else _PURGE_SECONDS
            if old.suffix in (".json", ".tmp") and time.time() - old.stat().st_mtime > limit:
                old.unlink()
        except OSError:
            pass


def read_sessions(state_dir: str | Path, now: float | None = None) -> list[dict[str, Any]]:
    """Registros validos e ainda dentro do TTL; arquivos ilegiveis ou malformados sao ignorados."""
    now = time.time() if now is None else now
    out = []
    try:
        files = list(Path(state_dir).glob("*.json"))
    except OSError:
        return out
    for f in files:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        ts = rec.get("ts")
        if (
            rec.get("state") in STATES
            and isinstance(ts, (int, float)) and not isinstance(ts, bool)
            and -_FUTURE_SKEW <= now - ts <= TTL_SECONDS[rec["state"]]
            and isinstance(rec.get("config_dir"), str)
        ):
            out.append(rec)
    return out


def aggregate(records: list[dict[str, Any]], config_dirs: set[str]) -> str:
    """Prioridade: aguardando > ocupada > ociosa; sem sessao valida, `unknown`."""
    states = {r["state"] for r in records if r["config_dir"] in config_dirs}
    for s in ("waiting", "busy", "idle"):
        if s in states:
            return s
    return "unknown"


def _claude_accounts(status: Any) -> list[dict[str, Any]]:
    agents = status.get("agents") if isinstance(status, dict) else None
    claude = agents.get("claude") if isinstance(agents, dict) else None
    accs = claude.get("accounts") if isinstance(claude, dict) else None
    return [a for a in accs if isinstance(a, dict)] if isinstance(accs, list) else []


def account_dirs(status: dict[str, Any], config: dict[str, Any]) -> dict[str, list[str]]:
    """Diretorios de configuracao cujas sessoes pertencem a cada Conta Claude: o do Perfil Isolado
    da Conta; a Conta Ativa no Sistema recebe tambem o diretorio padrao do sistema.
    """
    # import local: o hook roda isolado e so pode usar a biblioteca padrao
    from ai_usage_collector.config import get_accounts_for_agent
    from ai_usage_collector.history import account_log_dir

    own = {str(a.get("id")): account_log_dir("claude", a) for a in get_accounts_for_agent(config, "claude") if isinstance(a, dict)}
    out: dict[str, list[str]] = {}
    for acc in _claude_accounts(status):
        aid = str(acc.get("id"))
        dirs = [str(own[aid])] if own.get(aid) else []
        if acc.get("isActive") is True:
            dirs.append(str(claude_config_dir()))
        out[aid] = dirs
    return out


def states_from_dirs(dirs: dict[str, list[str]], state_dir: str | Path, now: float | None = None) -> dict[str, str]:
    """Estado por Conta (so biblioteca padrao). Vazio se os hooks nunca gravaram nada."""
    if not Path(state_dir).is_dir():
        return {}
    records = read_sessions(state_dir, now)
    return {aid: aggregate(records, set(d)) for aid, d in dirs.items()}


def apply_session_state(status: dict[str, Any], config: dict[str, Any], cache_path: str | Path, now: float | None = None) -> None:
    """Preenche `session_state` (campo opcional) nas Contas Claude do status e grava ao lado do
    status o mapa Conta -> diretorios, que o caminho leve (`states_main`) usa sem importar o coletor.
    """
    dirs = account_dirs(status, config)
    cache_dir = Path(cache_path).expanduser().resolve().parent
    tmp = cache_dir / f".{ACCOUNTS_FILENAME}.{os.getpid()}.tmp"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dirs, f)
    os.replace(tmp, cache_dir / ACCOUNTS_FILENAME)
    states = states_from_dirs(dirs, cache_dir / STATE_DIRNAME, now)
    for acc in _claude_accounts(status):
        if str(acc.get("id")) in states:
            acc["session_state"] = states[str(acc.get("id"))]


def live_states(cache_path: str | Path, now: float | None = None) -> dict[str, str]:
    """Estado ao vivo por Conta Claude, lido do mapa do ultimo refresh; tolera tudo malformado."""
    cache_dir = Path(cache_path).expanduser().resolve().parent
    try:
        dirs = json.loads((cache_dir / ACCOUNTS_FILENAME).read_text(encoding="utf-8"))
        dirs = {str(k): [d for d in v if isinstance(d, str)] for k, v in dirs.items() if isinstance(v, list)}
    except (OSError, ValueError, AttributeError):
        return {}
    return states_from_dirs(dirs, cache_dir / STATE_DIRNAME, now)


def states_main(argv: list[str] | None = None) -> int:
    """Entrypoint leve (`ai-usage-session-state [status.json]`): JSON `{"claude": {conta: estado}}`."""
    argv = sys.argv[1:] if argv is None else argv
    cache = argv[0] if argv else "~/.cache/plasma-ai-usage/status.json"
    sys.stdout.write(json.dumps({"claude": live_states(cache)}) + "\n")
    return 0


def _drain(stream: Any) -> None:
    """Le e descarta o resto da entrada (evita EPIPE no Claude Code), com limite de bytes e tempo."""
    total, deadline = 0, time.monotonic() + _DRAIN_MAX_SECONDS
    while total < _DRAIN_MAX_BYTES and time.monotonic() < deadline:
        chunk = stream.read(65536)
        if not chunk:
            return
        total += len(chunk)


def hook_main(argv: list[str]) -> int:
    """Corpo do hook: `<estado> <diretorio>`; qualquer falha e engolida (exit 0, sem saida)."""
    try:
        state, state_dir = argv[0], argv[1]
        raw = sys.stdin.buffer.read(_MAX_STDIN)
        _drain(sys.stdin.buffer)
        sid = ntype = None
        try:
            payload = json.loads(raw) if raw.strip() else {}
            payload = payload if isinstance(payload, dict) else {}
            sid, ntype = payload.get("session_id"), payload.get("notification_type")
        except ValueError:  # JSON truncado (entrada grande): so o prefixo, com regex restrita
            m, n = _SID_RE.search(raw[:_HEAD]), _NTYPE_RE.search(raw[:_HEAD])
            sid, ntype = m and m.group(1).decode(), n and n.group(1).decode()
        if state == "waiting" and ntype not in WAITING_NOTIFICATION_TYPES:
            return 0  # auth_success, idle_prompt, tipo ausente/desconhecido: nao espera o usuario
        write_event(state_dir, state, sid if isinstance(sid, str) and sid else "unknown")
    except BaseException:  # noqa: BLE001 - o hook nunca pode falhar o Claude Code
        pass
    return 0


if __name__ == "__main__":
    sys.exit(states_main(sys.argv[2:]) if sys.argv[1:2] == ["--states"] else hook_main(sys.argv[1:]))
