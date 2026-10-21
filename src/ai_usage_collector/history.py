"""Historico de Tokens: agregado diario por provedor, Conta e modelo, lido de forma incremental."""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from ai_usage_collector.config import DEFAULT_CACHE_DIR, credential_override, ensure_secure_dir, get_accounts_for_agent, save_secure_json
from ai_usage_collector.extractors.claude import parse_timestamp
from ai_usage_collector.identity import credential_identity

RETENTION_DAYS = 400
HISTORY_FILENAME = "history.json"
LOG_GLOBS = {"claude": "projects/**/*.jsonl", "codex": "sessions/**/rollout-*.jsonl"}
HISTORY_VERSION = 2  # v2: totais por Identidade da Conta (ADR-0008); v1 era por id da Conta
UNATTRIBUTED_ACCOUNT = "sistema"  # chave do v1 para logs do sistema sem dono
UNKNOWN_MODEL = "desconhecido"


def history_path_for(cache_path: str | Path | None) -> Path:
    """history.json fica ao lado do status.json."""
    base = Path(cache_path).expanduser().resolve().parent if cache_path else DEFAULT_CACHE_DIR
    return base / HISTORY_FILENAME


def system_log_dir(provider: str, override: Path | None = None) -> Path | None:
    """Diretorio de logs do sistema; com caminho de credenciais alternativo (ticket 38), a pasta dele."""
    if override:
        return override.parent
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


def account_key(provider: str, account: dict[str, Any]) -> str:
    """Chave do historico de uma Conta: a Identidade da Conta; sem identidade conhecida, o id."""
    from ai_usage_collector.capture import account_credential_file  # import local: capture importa config

    ident = credential_identity(provider, account_credential_file(provider, account))
    return ident.key if ident else str(account.get("id"))


def system_key(provider: str, accounts: list[dict[str, Any]], override: Path | None = None) -> str | None:
    """Chave de quem esta no caminho do sistema agora (None se desconhecido)."""
    from ai_usage_collector.capture import find_matching_account, get_active_credentials, get_system_credential_file

    sys_file = get_system_credential_file(provider, override)
    creds = get_active_credentials(provider, override)
    if creds is None:
        return None
    match = find_matching_account(provider, accounts, creds, sys_file)  # token prevalece sobre identidade defasada
    if match is not None:
        return account_key(provider, match)
    ident = credential_identity(provider, sys_file)
    return ident.key if ident else None


def _upgrade_v1(history: dict[str, Any], rekey: dict[tuple[str, str], str]) -> None:
    """Converte o historico por id de Conta em por identidade (Contas de mesma identidade somam).

    O acumulado sem dono ("sistema") vai para a identidade ativa agora, marcado como estimado.
    Sem identidade ativa para ele, a conversao fica pendente (versao 1) e e refeita na proxima coleta.
    """
    # ponytail: id de Conta ja removida/fundida antes da conversao fica sob o proprio id (so no export).
    for provs in history["daily"].values():
        for provider, accs in provs.items():
            merged: dict[str, dict[str, int]] = {}
            for old, models in accs.items():
                key = rekey.get((provider, old), old)
                if old == UNATTRIBUTED_ACCOUNT and key != old and key not in history["estimated"].setdefault(provider, []):
                    history["estimated"][provider].append(key)
                bucket = merged.setdefault(key, {})
                for model, tokens in models.items():
                    bucket[model] = bucket.get(model, 0) + tokens
            provs[provider] = merged
    history["system_seen"] = list(LOG_GLOBS)  # o v1 ja lia os logs do sistema
    pending = any(UNATTRIBUTED_ACCOUNT in accs for provs in history["daily"].values() for accs in provs.values())
    if not pending:
        history["version"] = HISTORY_VERSION


def _tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    except (ValueError, TypeError, OverflowError):
        return 0  # linha com contagem invalida nao pode abortar a leitura das demais


def _parse_claude(entry: dict[str, Any], cursor: dict[str, Any], seen: set[str]) -> tuple[str, int] | None:
    msg = entry.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    # O Claude Code repete a mesma mensagem (uma linha por bloco de conteudo, sessoes retomadas
    # copiadas para outro arquivo, arquivo reescrito): conta cada message.id:requestId uma vez.
    if msg.get("id"):
        key = f"{msg['id']}:{entry.get('requestId')}"
        if key in seen:
            return None
        seen.add(key)
    return str(msg.get("model") or UNKNOWN_MODEL), _tokens(msg["usage"])


def _parse_codex(entry: dict[str, Any], cursor: dict[str, Any], seen: set[str]) -> tuple[str, int] | None:
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


def _read_new_lines(
    path: Path, provider: str, account_id: str, history: dict[str, Any], cutoff_ts: float, seen: dict[str, set[str]]
) -> int:
    """Le o que ha de novo em `path`; devolve os tokens acrescentados."""
    added = 0
    cursor = history["cursors"].setdefault(str(path), {"offset": 0})
    st = path.stat()
    # Truncado/reescrito: recomeca (Claude protegido pelo dedup de ids).
    # ponytail: Codex e append-only; um rollout reescrito seria recontado.
    if st.st_size < cursor["offset"]:
        cursor.clear()
        cursor["offset"] = 0
    if st.st_size == cursor["offset"]:
        return 0
    if st.st_mtime < cutoff_ts:  # tudo alem da retencao
        cursor["offset"] = st.st_size
        return 0

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
        ts = parse_timestamp(entry.get("timestamp"))
        if ts is None:
            continue
        day = datetime.fromtimestamp(ts).date().isoformat()
        parsed = parser(entry, cursor, seen.setdefault(day, set()))
        if not parsed or parsed[1] <= 0:
            continue
        model, tokens = parsed
        bucket = history["daily"].setdefault(day, {}).setdefault(provider, {}).setdefault(account_id, {})
        bucket[model] = bucket.get(model, 0) + tokens
        added += tokens
    return added


def load_history(path: Path) -> dict[str, Any]:
    """Arquivo ausente -> vazio. Arquivo corrompido -> erro (nunca sobrescrever o historico)."""
    if not path.exists():
        return {"version": HISTORY_VERSION, "daily": {}, "cursors": {}, "seen": {}, "estimated": {}, "system_seen": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("daily"), dict):
        raise ValueError(f"Historico de Tokens invalido: {path}")
    data.setdefault("cursors", {})
    data.setdefault("seen", {})
    data.setdefault("estimated", {})
    data.setdefault("system_seen", [])
    version = data.setdefault("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError(f"Historico de Tokens com versao invalida: {path}")
    if version > HISTORY_VERSION:  # escrito por uma versao mais nova: nunca sobrescrever
        raise ValueError(f"Historico de Tokens de versao mais nova ({version}) que a suportada: {path}")
    return data


def update_history(
    sources: dict[Path, tuple[str, str]],
    path: Path,
    today: date,
    rekey: Callable[[], dict[tuple[str, str], str]] = dict,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Le o que ha de novo em cada diretorio de logs, aplica a retencao e salva (0600, atomico).

    `rekey` (so chamado se o arquivo ainda for v1) mapeia (provedor, id da Conta) -> identidade.

    Um lock ao lado do arquivo evita que coletas simultaneas percam incrementos.
    """
    ensure_secure_dir(path.parent)
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = load_history(path)
        if history["version"] < HISTORY_VERSION:
            _upgrade_v1(history, rekey())
        first_day = (today - timedelta(days=RETENTION_DAYS - 1)).isoformat()
        cutoff_ts = datetime.combine(date.fromisoformat(first_day), datetime.min.time()).timestamp()
        seen = {d: set(keys) for d, keys in history["seen"].items()}

        for log_dir, (provider, account_id) in sources.items():
            added = 0
            for file in sorted(log_dir.glob(LOG_GLOBS[provider])):
                try:
                    added += _read_new_lines(file, provider, account_id, history, cutoff_ts, seen)
                except OSError:
                    continue
            if log_dir == system_log_dir(provider, credential_override(provider, config) if config else None) and provider not in history["system_seen"]:
                # Primeira leitura do sistema: o acumulado antigo e da identidade ativa, sem como saber (estimado).
                history["system_seen"].append(provider)
                est = history["estimated"].setdefault(provider, [])
                if added and account_id not in est:
                    est.append(account_id)

        history["daily"] = {d: v for d, v in history["daily"].items() if d >= first_day}
        history["seen"] = {d: sorted(k) for d, k in seen.items() if k and d >= first_day}
        history["cursors"] = {p: c for p, c in history["cursors"].items() if Path(p).exists()}
        save_secure_json(history, path, prefix="history_")
    return history


def build_sources(config: dict[str, Any], only_system: bool = False) -> dict[Path, tuple[str, str]]:
    """Diretorio de logs -> (provedor, chave de identidade).

    Logs do caminho do sistema vao para quem esta nele agora; se for desconhecido, nao sao lidos
    (o cursor nao avanca e o consumo e atribuido na proxima leitura com identidade conhecida).
    """
    sources: dict[Path, tuple[str, str]] = {}
    for provider in LOG_GLOBS:
        accounts = get_accounts_for_agent(config, provider)
        if not accounts:
            continue
        if not only_system:
            for acc in accounts:
                d = account_log_dir(provider, acc)
                if d:
                    sources[d] = (provider, account_key(provider, acc))
        override = credential_override(provider, config)
        key = system_key(provider, accounts, override)
        if key:
            sources[system_log_dir(provider, override)] = (provider, key)
    return sources


def rekey_map(config: dict[str, Any]) -> dict[tuple[str, str], str]:
    """(provedor, id da Conta) -> chave por identidade, para converter o formato v1."""
    rekey = {}
    for provider in LOG_GLOBS:
        accounts = get_accounts_for_agent(config, provider)
        rekey.update({(provider, str(a.get("id"))): account_key(provider, a) for a in accounts})
        key = system_key(provider, accounts, credential_override(provider, config))
        if key:
            rekey[(provider, UNATTRIBUTED_ACCOUNT)] = key
    return rekey


def flush_system_history(config: dict[str, Any], cache_path: str | Path | None, now: datetime) -> None:
    """Fecha a leitura dos logs do sistema na identidade que esta saindo (chamar antes da Alternancia)."""
    update_history(
        build_sources(config, only_system=True), history_path_for(cache_path), now.astimezone().date(),
        lambda: rekey_map(config), config,
    )


def _first_of_month(d: date, back: int) -> date:
    m = d.year * 12 + d.month - 1 - back
    return date(m // 12, m % 12 + 1, 1)


def summarize(history: dict[str, Any], provider: str, keys: str | list[str], today: date) -> dict[str, Any]:
    """`keys`: chave(s) de historico da Conta (identidade e/ou id, que somam)."""
    keys = [keys] if isinstance(keys, str) else keys
    per_day: dict[str, int] = {}
    for day, provs in history["daily"].items():
        total = sum(sum((provs.get(provider, {}).get(k) or {}).values()) for k in keys)
        if total:
            per_day[day] = total

    def between(start: date, end: date) -> int:
        s, e = start.isoformat(), end.isoformat()
        return sum(v for d, v in per_day.items() if s <= d <= e)

    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "estimated": any(k in history.get("estimated", {}).get(provider, []) for k in keys),
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
    history = update_history(build_sources(config), history_path_for(cache_path), today, lambda: rekey_map(config), config)
    accounts = {(p, str(a.get("id"))): a for p in LOG_GLOBS for a in get_accounts_for_agent(config, p)}
    for provider, agent in status_payload["agents"].items():
        for acc in agent["accounts"]:
            cfg_acc = accounts.get((provider, str(acc["id"])))
            # Identidade + id: tokens lidos antes de a identidade ser conhecida ficam sob o id.
            keys = [str(acc["id"])]
            if cfg_acc and (key := account_key(provider, cfg_acc)) not in keys:
                keys.append(key)
            acc["token_history"] = summarize(history, provider, keys, today)


def export_history(cache_path: str | Path | None, fmt: str, config: dict[str, Any] | None = None) -> str:
    """Historico diario (ate 400 dias) em CSV ou JSON: date, provider, account, model, tokens.

    `account` e o id da Conta que hoje tem aquela identidade (ou "(conta removida) <hash>" se nenhuma tem).
    """
    history = load_history(history_path_for(cache_path))
    names: dict[tuple[str, str], str] = {}
    for p in LOG_GLOBS:
        for a in get_accounts_for_agent(config or {}, p):
            names.setdefault((p, str(a.get("id"))), str(a.get("id")))
            names.setdefault((p, account_key(p, a)), str(a.get("id")))

    def label(prov: str, key: str) -> str:
        # Identidade sem Conta hoje: nao expor email/uuid crus.
        return names.get((prov, key)) or f"(conta removida) {hashlib.sha256(f'{prov}:{key}'.encode()).hexdigest()[:8]}"

    rows = [
        {"date": day, "provider": prov, "account": label(prov, acc), "model": model, "tokens": tokens}
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
