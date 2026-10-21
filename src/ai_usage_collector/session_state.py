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
import sys
import time
from pathlib import Path
from typing import Any

STATES = ("busy", "waiting", "idle")
STATE_DIRNAME = "session-state"
# Sem Stop/heartbeat uma sessao morta nao pode ficar "ocupada" para sempre: o estado expira.
TTL_SECONDS = 1800
_PURGE_SECONDS = 86400
_MAX_STDIN = 1 << 20
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
    for old in d.glob("*.json"):
        try:
            if now - old.stat().st_mtime > _PURGE_SECONDS:
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
            and -_FUTURE_SKEW <= now - ts <= TTL_SECONDS
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


def session_states(status: dict[str, Any], config: dict[str, Any], state_dir: str | Path, now: float | None = None) -> dict[str, str]:
    """Estado por Conta Claude: sessoes do Perfil Isolado da Conta; a Conta Ativa no Sistema
    recebe tambem as do diretorio padrao do sistema. Vazio se os hooks nunca gravaram nada.
    """
    if not Path(state_dir).is_dir():
        return {}
    # import local: o hook roda isolado e so pode usar a biblioteca padrao
    from ai_usage_collector.config import get_accounts_for_agent
    from ai_usage_collector.history import account_log_dir

    records = read_sessions(state_dir, now)
    dirs = {str(a.get("id")): account_log_dir("claude", a) for a in get_accounts_for_agent(config, "claude")}
    out: dict[str, str] = {}
    for acc in ((status.get("agents") or {}).get("claude") or {}).get("accounts") or []:
        if not isinstance(acc, dict):
            continue
        wanted = set()
        if dirs.get(str(acc.get("id"))):
            wanted.add(str(dirs[str(acc.get("id"))]))
        if acc.get("isActive") is True:
            wanted.add(str(claude_config_dir()))
        out[str(acc.get("id"))] = aggregate(records, wanted)
    return out


def apply_session_state(status: dict[str, Any], config: dict[str, Any], state_dir: str | Path, now: float | None = None) -> None:
    """Preenche `session_state` (campo opcional) nas Contas Claude do status."""
    states = session_states(status, config, state_dir, now)
    for acc in ((status.get("agents") or {}).get("claude") or {}).get("accounts") or []:
        if isinstance(acc, dict) and str(acc.get("id")) in states:
            acc["session_state"] = states[str(acc.get("id"))]


def hook_main(argv: list[str]) -> int:
    """Corpo do hook: `<estado> <diretorio>`; qualquer falha e engolida (exit 0, sem saida)."""
    try:
        state, state_dir = argv[0], argv[1]
        raw = sys.stdin.buffer.read(_MAX_STDIN)
        payload = json.loads(raw) if raw.strip() else {}
        payload = payload if isinstance(payload, dict) else {}
        if state == "waiting" and payload.get("notification_type") == "idle_prompt":
            return 0  # lembrete de ociosidade do Claude: a sessao ja terminou, segue ociosa
        sid = payload.get("session_id")
        write_event(state_dir, state, sid if isinstance(sid, str) and sid else "unknown")
    except BaseException:  # noqa: BLE001 - o hook nunca pode falhar o Claude Code
        pass
    return 0


if __name__ == "__main__":
    sys.exit(hook_main(sys.argv[1:]))
