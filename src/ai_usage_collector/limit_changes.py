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


def _present(window: dict[str, Any], release_key: str) -> bool:
    return window.get("window_seconds") is not None or window.get(release_key) is not None


def _detect(name: str, old: dict[str, Any], new: dict[str, Any], now: datetime) -> str | None:
    key = _RELEASE_KEY[name]
    was, is_ = _present(old, key), _present(new, key)
    if was != is_:
        return "added" if is_ else "removed"
    if not is_:
        return None
    old_s, new_s = old.get("window_seconds"), new.get("window_seconds")
    if old_s is not None and new_s is not None and old_s != new_s:
        return "duration"
    old_r, new_r = _parse(old.get(key)), _parse(new.get(key))
    if old_r and new_r and old_r > now and new_r < old_r - EARLY_RESET_TOLERANCE:
        return "early_reset"
    return None


def apply_limit_changes(status: dict[str, Any], previous: dict[str, Any] | None, now: datetime) -> None:
    """Anexa `limit_changes` (campo opcional) as Contas com mudancas ainda dentro dos 3 dias."""
    old_accounts = {
        (p, str(a.get("id"))): a
        for p, agent in ((previous or {}).get("agents") or {}).items()
        for a in agent.get("accounts") or []
        if isinstance(a, dict)
    }
    for provider, agent in status["agents"].items():
        for acc in agent["accounts"]:
            old = old_accounts.get((provider, str(acc["id"])))
            changes = [
                c for c in (old or {}).get("limit_changes") or []
                if (exp := _parse(c.get("expires_at"))) and exp > now
            ]
            # Sem dado valido de um dos lados, ausencia de janela nao e mudanca de limite
            if old and old.get("health", {}).get("status") == "valid" and acc["health"].get("status") == "valid":
                for name, field in (("native", "native_window"), ("weekly", "weekly_window")):
                    if kind := _detect(name, old.get(field) or {}, acc[field], now):
                        changes.append({
                            "window": name, "kind": kind,
                            "detected_at": now.isoformat(), "expires_at": (now + NOTE_TTL).isoformat(),
                        })
            if changes:
                acc["limit_changes"] = changes
