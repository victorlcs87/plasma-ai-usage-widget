"""Nota de mudanca de limites: compara cada janela com o ultimo estado em cache (validade de 3 dias)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

NOTE_TTL = timedelta(days=3)
EARLY_RESET_TOLERANCE = timedelta(minutes=1)  # o horario informado pelo provedor oscila alguns segundos

_RELEASE_KEY = {"native": "release_time", "weekly": "cycle_reset_time"}


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _detect(name: str, old: dict[str, Any], new: dict[str, Any], now: datetime) -> str | None:
    """Compara so leituras de origem confiavel: `source` e "api" (bucket informado pelo provedor),
    "api_missing" (a API respondeu com outras janelas, mas sem esta) ou "local" (calculo local, ignorado).
    Duracao e reset so contam se `api_fields` diz que foram lidos da API, nao assumidos por padrao."""
    was, is_ = old.get("source"), new.get("source")
    if was == "api" and is_ == "api_missing":
        return "removed"
    if was == "api_missing" and is_ == "api":
        return "added"
    if was != "api" or is_ != "api":
        return None
    old_s, new_s = old.get("window_seconds"), new.get("window_seconds")
    both = set(old.get("api_fields") or []) & set(new.get("api_fields") or [])
    if "duration" in both and old_s is not None and new_s is not None and old_s != new_s:
        return "duration"
    key = _RELEASE_KEY[name]
    old_r, new_r = _parse(old.get(key)), _parse(new.get(key))
    if "release" in both and old_r and new_r and old_r > now and new_r < old_r - EARLY_RESET_TOLERANCE:
        return "early_reset"
    return None


def _account_changes(old: Any, acc: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    old = old if isinstance(old, dict) else {}
    changes = [
        c for c in old.get("limit_changes") or []
        if isinstance(c, dict) and (exp := _parse(c.get("expires_at"))) and exp > now
    ]
    # Sem dado valido de um dos lados, ausencia de janela nao e mudanca de limite
    if (old.get("health") or {}).get("status") == "valid" and acc["health"].get("status") == "valid":
        for name, field in (("native", "native_window"), ("weekly", "weekly_window")):
            if kind := _detect(name, old.get(field) or {}, acc[field], now):
                # Uma nota por (janela, tipo): a repeticao renova a validade em vez de duplicar
                changes = [c for c in changes if (c.get("window"), c.get("kind")) != (name, kind)]
                changes.append({
                    "window": name, "kind": kind,
                    "detected_at": now.isoformat(), "expires_at": (now + NOTE_TTL).isoformat(),
                })
    return changes


def apply_limit_changes(status: dict[str, Any], previous: Any, now: datetime) -> None:
    """Anexa `limit_changes` (campo opcional) as Contas com mudancas ainda dentro dos 3 dias.

    O cache anterior e nao confiavel: cada Conta e isolada, e uma entrada corrompida so perde a propria nota.
    """
    agents = previous.get("agents") if isinstance(previous, dict) else None
    for provider, agent in status["agents"].items():
        prev_agent = agents.get(provider) if isinstance(agents, dict) else None
        prev_accounts = prev_agent.get("accounts") if isinstance(prev_agent, dict) else None
        old_by_id = {
            str(a.get("id")): a for a in prev_accounts if isinstance(a, dict)
        } if isinstance(prev_accounts, list) else {}
        for acc in agent["accounts"]:
            try:
                changes = _account_changes(old_by_id.get(str(acc["id"])), acc, now)
            except Exception:
                continue
            if changes:
                acc["limit_changes"] = changes
