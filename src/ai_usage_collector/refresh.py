"""Atualizacao periodica por provedor (ADR-0007).

- Uma unica consulta HTTP por credencial (hash do token) em cada ciclo de coleta.
- HTTP 429 pausa a Conta (`provedor:id`) ate `retry-after`, com backoff exponencial; a pausa
  persiste em `refresh_state.json` (0600, ao lado do status.json; nunca guarda tokens) e
  sobrevive a renovacao do token.
- Falha de consulta serve o ultimo resultado valido (status.json anterior) da mesma
  Identidade da Conta, marcado como desatualizado. Sem esse cache, cada janela sem
  historico local proprio fica sem porcentagem (nunca 0% inventado); sem nenhuma, "sem dados".
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import http.client
import os
import json
import math
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ai_usage_collector.config import SUPPORTED_PROVIDERS, ensure_secure_dir, save_secure_json

STATE_FILENAME = "refresh_state.json"
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 86400
DEFAULT_INTERVAL_SECONDS = 300
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
MAX_PAUSE_SECONDS = 86400
MAX_FAILURES = 20  # 2 ** 20 ja excede BACKOFF_MAX_SECONDS

MESSAGES = {
    "rate_limited": "Limite de requisições do provedor atingido (HTTP 429); aguardando a pausa pedida.",
    "auth": "Login expirado ou revogado no provedor; faça login novamente.",
    "network": "Falha ao consultar o provedor (rede indisponível).",
    "invalid_response": "O provedor respondeu sem os dados de uso esperados.",
}
# Ordem de gravidade quando a mesma Conta acumula mais de um resultado no ciclo
_SEVERITY = {"ok": 0, "network": 1, "invalid_response": 1, "auth": 2, "rate_limited": 3}
_WINDOW_RESET_FIELDS = {"native_window": "release_time", "weekly_window": "cycle_reset_time"}

Validator = Callable[[dict[str, Any]], bool]


def utcnow() -> datetime:
    """Relogio do coletor (substituivel nos testes)."""
    return datetime.now(timezone.utc)


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return datetime.max.replace(tzinfo=timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def parse_intervals(values: Sequence[str] | None) -> dict[str, int]:
    """Converte ['claude=300', ...] em segundos, limitando a [60, 86400]."""
    intervals: dict[str, int] = {}
    for raw in values or []:
        prov, sep, secs = str(raw).partition("=")
        prov = prov.strip().lower()
        if not sep or prov not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Intervalo de Atualização inválido '{raw}'. Use PROVEDOR=SEGUNDOS, "
                f"com PROVEDOR em {', '.join(SUPPORTED_PROVIDERS)}."
            )
        try:
            seconds = int(secs)
        except ValueError:
            raise ValueError(f"Intervalo de Atualização inválido '{raw}': segundos devem ser um número inteiro.") from None
        intervals[prov] = min(MAX_INTERVAL_SECONDS, max(MIN_INTERVAL_SECONDS, seconds))
    return intervals


class FetchError(Exception):
    def __init__(self, kind: str, retry_after: float | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.retry_after = retry_after


def _retry_after_seconds(headers: Any, now: datetime) -> float | None:
    """Segundos pedidos pelo provedor, limitados a [0, 1 dia]; None se ausente ou invalido."""
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - now).total_seconds()
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_PAUSE_SECONDS)


def request_json(
    request: urllib.request.Request,
    timeout: float,
    now: datetime | None = None,
    valid: Validator | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any]:
    """Executa a requisicao e devolve o JSON; erros viram FetchError classificado.

    `opener` permite um OpenerDirector proprio (ex.: sem seguir redirects); o padrao e urlopen.
    """
    try:
        with (opener.open if opener else urllib.request.urlopen)(request, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or (resp.getcode() if hasattr(resp, "getcode") else None)
            if status not in (200, 201):
                raise FetchError("invalid_response")
            body = resp.read()
            data = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise FetchError("rate_limited", _retry_after_seconds(e.headers, now or utcnow())) from None
        raise FetchError("auth" if e.code in (401, 403) else "network") from None
    except ValueError:  # JSON invalido
        raise FetchError("invalid_response") from None
    except (OSError, http.client.HTTPException):  # URLError, timeout, IncompleteRead, BadStatusLine
        raise FetchError("network") from None
    if not isinstance(data, dict) or (valid is not None and not valid(data)):
        raise FetchError("invalid_response")
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Nunca segue redirects: credenciais nao podem ser reenviadas a outro host."""

    def redirect_request(self, *args, **kwargs):
        return None


# Opener compartilhado (Claude e verificacao de atualizacao): 3xx vira HTTPError
NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_state(path: Path, now_ts: float) -> dict[str, dict[str, Any]]:
    """Pausas validas do arquivo de estado; entradas corrompidas sao descartadas.

    `paused_until` fica limitado a now + MAX_PAUSE_SECONDS (relogio recuado ou valor hostil)."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    creds = loaded.get("credentials") if isinstance(loaded, dict) else None
    state: dict[str, dict[str, Any]] = {}
    for key, entry in (creds.items() if isinstance(creds, dict) else []):
        paused_until = _finite(entry.get("paused_until")) if isinstance(entry, dict) else None
        if paused_until is None or paused_until < 0:
            continue
        failures = _finite(entry.get("failures"))
        state[str(key)] = {
            "paused_until": min(paused_until, now_ts + MAX_PAUSE_SECONDS),
            "failures": min(int(failures), MAX_FAILURES) if failures and failures > 0 else 0,
        }
    return state


class RefreshCycle:
    """Estado de um ciclo de coleta: memo por credencial e pausas por Conta."""

    def __init__(self, state_path: Path, now: datetime) -> None:
        self.state_path = state_path
        self.now = now
        self.state = _load_state(state_path, now.timestamp())
        self._memo: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] = {}
        self._pending: list[dict[str, Any]] = []
        self._account_key: str | None = None

    def begin_account(self, provider: str, account_id: str) -> None:
        """Associa as proximas consultas a esta Conta (chave da pausa)."""
        self._account_key = f"{provider}:{account_id}"
        self._pending = []

    def fetch(
        self,
        provider: str,
        secret: str,
        request: urllib.request.Request,
        timeout: float,
        valid: Validator | None = None,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> dict[str, Any] | None:
        credential = f"{provider}:{_hash(secret)}"
        pause_key = self._account_key or credential
        now_ts = self.now.timestamp()
        entry = self.state.get(pause_key) or {}
        if entry.get("paused_until", 0) > now_ts:
            data, outcome = None, {"kind": "rate_limited", "retry_at": entry["paused_until"]}
        else:
            if credential not in self._memo:
                self._memo[credential] = self._request(request, timeout, valid, int(entry.get("failures") or 0), opener)
            data, outcome = self._memo[credential]
            if outcome["kind"] == "rate_limited":
                self.state[pause_key] = {"paused_until": outcome["retry_at"], "failures": outcome["failures"]}
            elif outcome["kind"] == "ok":
                self.state.pop(pause_key, None)
        self._pending.append({**outcome, "credential": credential})
        return copy.deepcopy(data)

    def _request(self, request: urllib.request.Request, timeout: float, valid: Validator | None, failures: int, opener=None):
        try:
            return request_json(request, timeout, self.now, valid, opener), {"kind": "ok"}
        except FetchError as e:
            if e.kind != "rate_limited":
                return None, {"kind": e.kind}
            failures = min(failures + 1, MAX_FAILURES)
            backoff = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (failures - 1))
            paused_until = self.now.timestamp() + max(backoff, e.retry_after or 0)
            return None, {"kind": "rate_limited", "retry_at": paused_until, "failures": failures}

    def take_outcome(self) -> dict[str, Any] | None:
        """Resultado mais grave das consultas feitas desde a chamada anterior (None se nenhuma)."""
        pending, self._pending = self._pending, []
        return max(pending, key=lambda o: _SEVERITY[o["kind"]]) if pending else None

    def save(self) -> None:
        # Descarta pausas vencidas ha mais de um dia (Contas removidas deixam chaves orfas)
        cutoff = self.now.timestamp() - 86400
        creds = {k: v for k, v in self.state.items() if v["paused_until"] > cutoff}
        save_secure_json({"version": 2, "credentials": creds}, self.state_path, prefix="refresh_")


def forget_account(state_path: Path, provider: str, account_id: str) -> None:
    """Remove a pausa da Conta (chamar sob status_lock)."""
    cycle_ = RefreshCycle(state_path, utcnow())
    if cycle_.state.pop(f"{provider}:{account_id}", None) is not None:
        cycle_.save()


@contextmanager
def status_lock(state_path: Path) -> Iterator[None]:
    """Lock exclusivo (flock) que serializa quem regrava status.json e o estado de pausa."""
    ensure_secure_dir(state_path.parent)
    fd = os.open(state_path.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


_current: RefreshCycle | None = None


@contextmanager
def cycle(state_path: Path, now: datetime) -> Iterator[RefreshCycle]:
    """Ativa um ciclo de coleta sob o lock do status.json."""
    global _current
    with status_lock(state_path):
        # ponytail: ciclo global por processo; o coletor e um CLI de execucao unica
        _current = RefreshCycle(state_path, now)
        try:
            yield _current
        finally:
            # Grava tambem em excecao: a pausa aprendida num 429 nao pode se perder
            try:
                _current.save()
            finally:
                _current = None


def fetch_json(
    provider: str,
    secret: str,
    request: urllib.request.Request,
    timeout: float,
    valid: Validator | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any] | None:
    """Ponto unico de consulta HTTP dos extratores; fora de um ciclo, falhas viram None."""
    if _current is not None:
        return _current.fetch(provider, secret, request, timeout, valid, opener)
    try:
        return request_json(request, timeout, valid=valid, opener=opener)
    except FetchError:
        return None


def apply_outcome(
    entry: dict[str, Any],
    outcome: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    now: datetime,
    interval: int,
    identity_key: str | None = None,
) -> dict[str, Any]:
    """Acrescenta fetched_at/stale/next_check_at a uma Conta e trata falhas de consulta.

    `identity_key` (Identidade da Conta, identity.py) define de quem e o cache; sem ela,
    vale o hash da credencial consultada.
    """
    if outcome is None:  # nenhuma consulta a API (sem token ou login invalido): contrato inalterado
        return entry
    fingerprint = _hash(identity_key) if identity_key else outcome["credential"]
    entry["credential_fingerprint"] = fingerprint
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

    if previous and previous.get("fetched_at") and previous.get("credential_fingerprint") == fingerprint:
        for key in ("native_window", "weekly_window", "usage_details", "fetched_at"):
            if key in previous:
                entry[key] = previous[key]
            else:
                entry.pop(key, None)
        return entry

    # Sem cache da mesma Identidade: so vale a heuristica da janela com historico local proprio
    with_history = 0
    for window, reset_field in _WINDOW_RESET_FIELDS.items():
        data = entry.get(window)
        if not isinstance(data, dict):
            continue
        if data.get("messages_used"):
            with_history += 1
            continue
        prev_win = (previous or {}).get(window)
        baseline = {}
        if isinstance(prev_win, dict) and prev_win.get("source") in ("api", "api_missing"):
            # Linha de base de limit_changes: a ultima leitura da API nao se perde com "Sem dados"
            baseline = {k: prev_win[k] for k in ("source", "api_fields", "window_seconds") if k in prev_win}
        data.update({
            **baseline,
            "usage_percentage": None,
            "used_capacity": None,
            "available_capacity": None,
            reset_field: None,
            "seconds_remaining": None,
        })
    if not with_history:
        entry["no_data"] = True
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
