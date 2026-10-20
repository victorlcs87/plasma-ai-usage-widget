"""Historico de Tokens: agregado diario por provedor, Conta e modelo, lido de forma incremental."""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_usage_collector.config import DEFAULT_CACHE_DIR, get_accounts_for_agent, save_secure_json
from ai_usage_collector.extractors.claude import parse_timestamp

RETENTION_DAYS = 400
HISTORY_FILENAME = "history.json"
LOG_GLOBS = {"claude": "projects/**/*.jsonl", "codex": "sessions/**/rollout-*.jsonl"}
UNATTRIBUTED_ACCOUNT = "sistema"
UNKNOWN_MODEL = "desconhecido"


def history_path_for(cache_path: str | Path | None) -> Path:
    """history.json fica ao lado do status.json."""
    base = Path(cache_path).expanduser().resolve().parent if cache_path else DEFAULT_CACHE_DIR
    return base / HISTORY_FILENAME


def system_log_dir(provider: str) -> Path | None:
    if provider == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser().resolve()
    if provider == "codex":
        return Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser().resolve()
    return None


def account_log_dir(provider: str, account: dict[str, Any]) -> Path | None:
    """Mesmo criterio dos extratores para achar o diretorio do Perfil Isolado."""
    if account.get(f"{provider}_dir"):
        return Path(account[f"{provider}_dir"]).expanduser().resolve()
    cred = account.get("credential_path") or account.get("credentials_path")
    if cred:
        p = Path(cred).expanduser().resolve()
        return p.parent if p.is_file() or p.suffix == ".json" else p
    return None


def _tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)


def _parse_claude(entry: dict[str, Any], cursor: dict[str, Any]) -> tuple[str, int] | None:
    msg = entry.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    # O Claude Code grava uma linha por bloco de conteudo com o mesmo usage; conta uma vez.
    # ponytail: dedup so de linhas consecutivas; set global de ids se sessoes retomadas duplicarem.
    key = f"{msg.get('id')}:{entry.get('requestId')}"
    if msg.get("id") and key == cursor.get("last"):
        return None
    cursor["last"] = key
    return str(msg.get("model") or UNKNOWN_MODEL), _tokens(msg["usage"])


def _parse_codex(entry: dict[str, Any], cursor: dict[str, Any]) -> tuple[str, int] | None:
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    if entry.get("type") == "turn_context" and payload.get("model"):
        cursor["model"] = str(payload["model"])
        return None
    if payload.get("type") != "token_count" or not isinstance(payload.get("info"), dict):
        return None
    info = payload["info"]
    total = (info.get("total_token_usage") or {}).get("total_tokens")
    if total is not None and total == cursor.get("last"):
        return None  # evento repetido
    cursor["last"] = total
    return cursor.get("model") or UNKNOWN_MODEL, _tokens(info.get("last_token_usage"))


PARSERS = {"claude": _parse_claude, "codex": _parse_codex}


def _read_new_lines(path: Path, provider: str, account_id: str, history: dict[str, Any], cutoff_ts: float) -> None:
    cursor = history["cursors"].setdefault(str(path), {"offset": 0})
    st = path.stat()
    if st.st_size < cursor["offset"]:  # arquivo truncado/reescrito: recomeca
        cursor.clear()
        cursor["offset"] = 0
    if st.st_size == cursor["offset"]:
        return
    if st.st_mtime < cutoff_ts:  # tudo alem da retencao
        cursor["offset"] = st.st_size
        return

    with open(path, "rb") as f:
        f.seek(cursor["offset"])
        data = f.read()
    end = data.rfind(b"\n") + 1  # linha parcial fica para a proxima leitura
    cursor["offset"] += end

    parser = PARSERS[provider]
    for raw in data[:end].splitlines():
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        parsed = parser(entry, cursor)
        ts = parse_timestamp(entry.get("timestamp"))
        if not parsed or parsed[1] <= 0 or ts is None:
            continue
        model, tokens = parsed
        day = datetime.fromtimestamp(ts).date().isoformat()
        bucket = history["daily"].setdefault(day, {}).setdefault(provider, {}).setdefault(account_id, {})
        bucket[model] = bucket.get(model, 0) + tokens


def load_history(path: Path) -> dict[str, Any]:
    """Arquivo ausente -> vazio. Arquivo corrompido -> erro (nunca sobrescrever o historico)."""
    if not path.exists():
        return {"version": 1, "daily": {}, "cursors": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("daily"), dict):
        raise ValueError(f"Historico de Tokens invalido: {path}")
    data.setdefault("cursors", {})
    return data


def update_history(sources: dict[Path, tuple[str, str]], path: Path, today: date) -> dict[str, Any]:
    """Le o que ha de novo em cada diretorio de logs, aplica a retencao e salva (0600, atomico)."""
    history = load_history(path)
    first_day = today - timedelta(days=RETENTION_DAYS - 1)
    cutoff_ts = datetime.combine(first_day, datetime.min.time()).timestamp()

    for log_dir, (provider, account_id) in sources.items():
        for file in sorted(log_dir.glob(LOG_GLOBS[provider])):
            try:
                _read_new_lines(file, provider, account_id, history, cutoff_ts)
            except OSError:
                continue

    history["daily"] = {d: v for d, v in history["daily"].items() if d >= first_day.isoformat()}
    history["cursors"] = {p: c for p, c in history["cursors"].items() if Path(p).exists()}
    save_secure_json(history, path, prefix="history_")
    return history


def build_sources(config: dict[str, Any], status_payload: dict[str, Any]) -> dict[Path, tuple[str, str]]:
    """Diretorio de logs -> (provedor, Conta). Logs do caminho do sistema vao para a Conta Ativa no Sistema."""
    # ponytail: atribuicao no momento da leitura; trocas entre coletas podem atribuir a Conta errada.
    sources: dict[Path, tuple[str, str]] = {}
    for provider in LOG_GLOBS:
        accounts = get_accounts_for_agent(config, provider)
        if not accounts:
            continue
        for acc in accounts:
            d = account_log_dir(provider, acc)
            if d:
                sources[d] = (provider, str(acc.get("id")))
        active = next(
            (a["id"] for a in status_payload["agents"][provider]["accounts"] if a.get("isActive")), None
        )
        sys_dir = system_log_dir(provider)
        if active is not None:
            sources[sys_dir] = (provider, str(active))
        else:
            sources.setdefault(sys_dir, (provider, UNATTRIBUTED_ACCOUNT))
    return sources


def _first_of_month(d: date, back: int) -> date:
    m = d.year * 12 + d.month - 1 - back
    return date(m // 12, m % 12 + 1, 1)


def summarize(history: dict[str, Any], provider: str, account_id: str, today: date) -> dict[str, Any]:
    per_day: dict[str, int] = {}
    for day, provs in history["daily"].items():
        total = sum((provs.get(provider, {}).get(account_id) or {}).values())
        if total:
            per_day[day] = total

    def between(start: date, end: date) -> int:
        s, e = start.isoformat(), end.isoformat()
        return sum(v for d, v in per_day.items() if s <= d <= e)

    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "today": per_day.get(today.isoformat(), 0),
        "week": between(week_start, today),
        "month": between(month_start, today),
        "daily_30d": [
            {"date": (today - timedelta(days=i)).isoformat(), "tokens": per_day.get((today - timedelta(days=i)).isoformat(), 0)}
            for i in range(29, -1, -1)
        ],
        "weekly_3m": [
            {"week_start": (week_start - timedelta(weeks=i)).isoformat(),
             "tokens": between(week_start - timedelta(weeks=i), week_start - timedelta(weeks=i) + timedelta(days=6))}
            for i in range(12, -1, -1)
        ],
        "monthly_12m": [
            {"month": _first_of_month(today, i).isoformat()[:7],
             "tokens": between(_first_of_month(today, i), _first_of_month(today, i - 1) - timedelta(days=1))}
            for i in range(11, -1, -1)
        ],
    }


def apply_token_history(
    status_payload: dict[str, Any], config: dict[str, Any], cache_path: str | Path | None, now: datetime
) -> None:
    """Atualiza o history.json e anexa `token_history` (campo opcional) a cada Conta do status."""
    today = now.astimezone().date()
    history = update_history(build_sources(config, status_payload), history_path_for(cache_path), today)
    for provider, agent in status_payload["agents"].items():
        for acc in agent["accounts"]:
            acc["token_history"] = summarize(history, provider, str(acc["id"]), today)


def export_history(cache_path: str | Path | None, fmt: str) -> str:
    """Historico diario (ate 400 dias) em CSV ou JSON: date, provider, account, model, tokens."""
    history = load_history(history_path_for(cache_path))
    rows = [
        {"date": day, "provider": prov, "account": acc, "model": model, "tokens": tokens}
        for day, provs in sorted(history["daily"].items())
        for prov, accs in sorted(provs.items())
        for acc, models in sorted(accs.items())
        for model, tokens in sorted(models.items())
    ]
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["date", "provider", "account", "model", "tokens"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()
