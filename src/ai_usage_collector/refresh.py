"""Atualizacao periodica por provedor (ADR-0007).

- Uma unica consulta HTTP por credencial em cada ciclo de coleta.
- HTTP 429 pausa a credencial ate `retry-after`, com backoff exponencial; a pausa
  persiste em `refresh_state.json` (0600, ao lado do status.json; so hashes, nunca tokens).
- Falha de consulta serve o ultimo resultado valido (status.json anterior) marcado como
  desatualizado; sem cache e sem historico local, a Conta fica "sem dados" (nunca 0% inventado).
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from ai_usage_collector.config import ensure_secure_dir, save_secure_json

STATE_FILENAME = "refresh_state.json"
MIN_INTERVAL_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 300
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600

MESSAGES = {
    "rate_limited": "Limite de requisições do provedor atingido (HTTP 429); aguardando a pausa pedida.",
    "auth": "Login expirado ou revogado no provedor; faça login novamente.",
    "network": "Falha ao consultar o provedor (rede indisponível ou resposta inválida).",
}
# Ordem de gravidade quando a mesma Conta acumula mais de um resultado no ciclo
_SEVERITY = {"ok": 0, "network": 1, "auth": 2, "rate_limited": 3}


def utcnow() -> datetime:
    """Relogio do coletor (substituivel nos testes)."""
    return datetime.now(timezone.utc)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def parse_intervals(values: Sequence[str] | None) -> dict[str, int]:
    """Converte ['claude=300', ...] em segundos, aplicando o minimo de 60 s."""
    intervals: dict[str, int] = {}
    for raw in values or []:
        prov, sep, secs = str(raw).partition("=")
        if not sep:
            raise ValueError(f"Intervalo inválido '{raw}'. Use PROVEDOR=SEGUNDOS.")
        intervals[prov.strip().lower()] = max(MIN_INTERVAL_SECONDS, int(secs))
    return intervals


class FetchError(Exception):
    def __init__(self, kind: str, retry_after: float | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.retry_after = retry_after


def _retry_after_seconds(headers: Any, now: datetime) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, (parsedate_to_datetime(value) - now).total_seconds())
    except (TypeError, ValueError):
        return None


def request_json(request: urllib.request.Request, timeout: float, now: datetime | None = None) -> dict[str, Any]:
    """Executa a requisicao e devolve o JSON; erros viram FetchError classificado."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or (resp.getcode() if hasattr(resp, "getcode") else None)
            if status in (200, 201):
                body = resp.read()
                data = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
                if isinstance(data, dict):
                    return data
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise FetchError("rate_limited", _retry_after_seconds(e.headers, now or utcnow())) from None
        raise FetchError("auth" if e.code in (401, 403) else "network") from None
    except (OSError, ValueError):  # URLError, timeout, JSON invalido
        raise FetchError("network") from None
    raise FetchError("network")


class RefreshCycle:
    """Estado de um ciclo de coleta: memo por credencial e pausas persistidas."""

    def __init__(self, state_path: Path, now: datetime) -> None:
        self.state_path = state_path
        self.now = now
        self.state: dict[str, Any] = {}
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded.get("credentials"), dict):
                self.state = loaded["credentials"]
        except (OSError, ValueError, AttributeError):
            pass
        self._memo: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] = {}
        self._pending: list[dict[str, Any]] = []

    def fetch(self, provider: str, secret: str, request: urllib.request.Request, timeout: float) -> dict[str, Any] | None:
        key = f"{provider}:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:16]}"
        if key not in self._memo:
            self._memo[key] = self._fetch_uncached(key, request, timeout)
        data, outcome = self._memo[key]
        self._pending.append(outcome)
        return copy.deepcopy(data)

    def _fetch_uncached(self, key: str, request: urllib.request.Request, timeout: float):
        now_ts = self.now.timestamp()
        entry = self.state.get(key) or {}
        paused_until = float(entry.get("paused_until") or 0)
        if paused_until > now_ts:
            return None, {"kind": "rate_limited", "retry_at": paused_until}
        try:
            data = request_json(request, timeout, self.now)
        except FetchError as e:
            if e.kind != "rate_limited":
                return None, {"kind": e.kind}
            failures = int(entry.get("failures") or 0) + 1
            backoff = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (failures - 1))
            paused_until = now_ts + max(backoff, e.retry_after or 0)
            self.state[key] = {"paused_until": paused_until, "failures": failures}
            return None, {"kind": "rate_limited", "retry_at": paused_until}
        self.state.pop(key, None)
        return data, {"kind": "ok"}

    def take_outcome(self) -> dict[str, Any] | None:
        """Resultado mais grave das consultas feitas desde a chamada anterior (None se nenhuma)."""
        pending, self._pending = self._pending, []
        return max(pending, key=lambda o: _SEVERITY[o["kind"]]) if pending else None

    def save(self) -> None:
        # Descarta pausas vencidas ha mais de um dia (tokens renovados deixam chaves orfas)
        cutoff = self.now.timestamp() - 86400
        creds = {k: v for k, v in self.state.items() if float(v.get("paused_until") or 0) > cutoff}
        save_secure_json({"version": 1, "credentials": creds}, self.state_path, prefix="refresh_")


_current: RefreshCycle | None = None


@contextmanager
def cycle(state_path: Path, now: datetime) -> Iterator[RefreshCycle]:
    """Ativa um ciclo de coleta; serializa coletores concorrentes com flock."""
    global _current
    ensure_secure_dir(state_path.parent)
    with open(state_path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # ponytail: ciclo global por processo; o coletor e um CLI de execucao unica
        _current = RefreshCycle(state_path, now)
        try:
            yield _current
            _current.save()
        finally:
            _current = None


def fetch_json(provider: str, secret: str, request: urllib.request.Request, timeout: float) -> dict[str, Any] | None:
    """Ponto unico de consulta HTTP dos extratores; fora de um ciclo, falhas viram None."""
    if _current is not None:
        return _current.fetch(provider, secret, request, timeout)
    try:
        return request_json(request, timeout)
    except FetchError:
        return None


def _has_local_history(entry: dict[str, Any]) -> bool:
    return any((entry.get(w) or {}).get("messages_used") for w in ("native_window", "weekly_window"))


def apply_outcome(
    entry: dict[str, Any],
    outcome: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    now: datetime,
    interval: int,
) -> dict[str, Any]:
    """Acrescenta fetched_at/stale/next_check_at a uma Conta e trata falhas de consulta."""
    if outcome is None:  # nenhuma consulta a API (sem token ou login invalido): contrato inalterado
        return entry
    retry_at = outcome.get("retry_at")
    entry["next_check_at"] = _iso(max(now.timestamp() + interval, retry_at or 0))
    if outcome["kind"] == "ok":
        entry["fetched_at"] = now.isoformat()
        entry["stale"] = False
        return entry

    entry["stale"] = True
    entry["fetch_error"] = {
        "kind": outcome["kind"],
        "message": MESSAGES[outcome["kind"]],
        "retry_at": _iso(retry_at) if retry_at else None,
    }
    if outcome["kind"] == "auth":
        entry["health"] = {**entry.get("health", {}), "status": "session_expired", "message": MESSAGES["auth"]}

    if previous and previous.get("fetched_at"):
        for key in ("native_window", "weekly_window", "usage_details", "fetched_at"):
            if key in previous:
                entry[key] = previous[key]
            else:
                entry.pop(key, None)
    elif not _has_local_history(entry):
        entry["no_data"] = True
        for w in ("native_window", "weekly_window"):
            entry[w].update({"used_capacity": None, "available_capacity": None})
    return entry


def summarize_agent(agent: dict[str, Any]) -> None:
    """Campos opcionais por provedor a partir das Contas consultadas neste ciclo."""
    accs = [a for a in agent.get("accounts", []) if a.get("next_check_at")]
    if not accs:
        return
    agent["stale"] = any(a.get("stale") for a in accs)
    agent["next_check_at"] = min((a["next_check_at"] for a in accs), key=datetime.fromisoformat)
    fetched = [a["fetched_at"] for a in accs if a.get("fetched_at")]
    if fetched:
        agent["fetched_at"] = max(fetched, key=datetime.fromisoformat)
