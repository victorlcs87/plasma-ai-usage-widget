"""Canonical status.json data contract definitions and validations."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# Fallback Native Window type when an extractor reports none; the provider's duration takes precedence
AGENT_NATIVE_WINDOWS: dict[str, str] = {
    "claude": "5h",
    "codex": "3h",
    "gemini": "daily",
}

# v2: optional per-account "usage_details" and "token_history" (absent when nothing was collected)
#     usage_details.quota_by_model (Gemini, ticket 29) is a new optional key of that field: no version bump
# v3: optional "window_seconds" and "elapsed_fraction" on native_window/weekly_window
CONTRACT_VERSION = 3
SUPPORTED_CONTRACT_VERSIONS = (1, 2, 3)

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_NAMED_WINDOWS = {"daily": 86400, "weekly": 604800}
MAX_WINDOW_SECONDS = 366 * 86400  # sanity ceiling for provider-reported durations

AGENT_NAMES: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
}


def get_current_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def parse_window_seconds(value: Any) -> int | None:
    """Window duration in seconds from 18000, "18000", "18000s", "5h", "7d", "daily" or "weekly".

    Returns None for unknown, non-positive, sub-second, non-finite or absurd (> 1 year) values.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _NAMED_WINDOWS:
            return _NAMED_WINDOWS[text]
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([smhdw]?)", text)
        if not match:
            return None
        value = float(match.group(1)) * _UNIT_SECONDS[match.group(2) or "s"]
    # Range check also rejects NaN, +/-Infinity and huge ints before int() can overflow
    if not isinstance(value, (int, float)) or not 1 <= value <= MAX_WINDOW_SECONDS:
        return None
    return int(value)


def window_type_from_seconds(seconds: int) -> str:
    """Short label for a window duration ("30s", "90m", "5h", "daily", "7d")."""
    if seconds == 86400:
        return "daily"
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _elapsed_fraction(window: dict[str, Any]) -> float | None:
    """Fraction of the window already elapsed, from its duration and the time until release."""
    total = window.get("window_seconds")
    remaining = window.get("seconds_remaining")
    if not isinstance(total, (int, float)) or total <= 0 or not isinstance(remaining, (int, float)):
        return None
    return round(min(1.0, max(0.0, 1.0 - remaining / total)), 4)


def build_empty_status_contract(now_iso: str | None = None) -> dict[str, Any]:
    """Construct an initial or empty canonical status.json payload."""
    timestamp = now_iso or get_current_iso_timestamp()
    return {
        "version": CONTRACT_VERSION,
        "last_updated": timestamp,
        "status": "ok",
        "agents": {
            agent_id: {
                "name": AGENT_NAMES.get(agent_id, agent_id.capitalize()),
                "status": "ok",
                "accounts": [],
            }
            for agent_id in ["claude", "codex", "gemini"]
        },
    }


def build_agent_account_status(
    provider: str,
    account_id: str,
    label: str,
    source: str,
    health: dict[str, Any],
    manual_invite_url: str | None = None,
    native_window: dict[str, Any] | None = None,
    weekly_window: dict[str, Any] | None = None,
    free_trial_invites: dict[str, Any] | None = None,
    name: str | None = None,
    manual_invite_count: int | None = None,
    is_active: bool = False,
    usage_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized account entry for the status contract."""
    window_type = AGENT_NATIVE_WINDOWS.get(provider.lower(), "custom")

    default_native_window: dict[str, Any] = {
        "type": window_type,
        "total_capacity": None,
        "used_capacity": None,
        "available_capacity": None,
        "usage_percentage": 0.0,
        "release_time": None,
        "seconds_remaining": None,
        "window_seconds": None,
    }
    if native_window:
        default_native_window.update(native_window)
    default_native_window["elapsed_fraction"] = _elapsed_fraction(default_native_window)

    default_weekly_window: dict[str, Any] = {
        "total_tokens_or_turns": None,
        "total_capacity": None,
        "used_capacity": None,
        "available_capacity": None,
        "usage_percentage": 0.0,
        "cycle_reset_time": None,
        "seconds_remaining": None,
        "window_seconds": None,
    }
    if weekly_window:
        default_weekly_window.update(weekly_window)
        if default_weekly_window.get("usage_percentage") is not None:
            try:
                default_weekly_window["usage_percentage"] = float(round(default_weekly_window["usage_percentage"], 1))
            except (ValueError, TypeError):
                default_weekly_window["usage_percentage"] = 0.0
        else:
            default_weekly_window["usage_percentage"] = 0.0
    default_weekly_window["elapsed_fraction"] = _elapsed_fraction(default_weekly_window)

    default_invites: dict[str, Any] = {
        "available_count": manual_invite_count if manual_invite_count is not None else 0,
        "invite_url": manual_invite_url,
    }
    if free_trial_invites:
        default_invites.update(free_trial_invites)
        # Ensure manual overrides are preserved if extractor didn't find them
        if not default_invites.get("invite_url") and manual_invite_url:
            default_invites["invite_url"] = manual_invite_url
        if manual_invite_count is not None and default_invites.get("available_count") == 0:
            default_invites["available_count"] = manual_invite_count

    account_name = name or label

    entry = {
        "id": account_id,
        "name": account_name,
        "label": label,
        "provider": provider,
        "source": source,
        "isActive": bool(is_active),
        "health": health,
        "native_window": default_native_window,
        "weekly_window": default_weekly_window,
        "free_trial_invites": default_invites,
    }
    if usage_details:
        entry["usage_details"] = usage_details
    return entry


def validate_status_contract(data: Any) -> bool:
    """Validate that data conforms to canonical status contract specification."""
    if not isinstance(data, dict):
        return False

    if data.get("version") not in SUPPORTED_CONTRACT_VERSIONS:
        return False

    if not isinstance(data.get("last_updated"), str):
        return False

    if not isinstance(data.get("status"), str):
        return False

    agents = data.get("agents")
    if not isinstance(agents, dict):
        return False

    orphans = data.get("orphan_profiles")
    if orphans is not None and not (isinstance(orphans, list) and all(isinstance(o, dict) for o in orphans)):
        return False

    for required_agent in ["claude", "codex", "gemini"]:
        if required_agent not in agents:
            return False
        agent_data = agents[required_agent]
        if not isinstance(agent_data, dict):
            return False
        if "name" not in agent_data or "status" not in agent_data or "accounts" not in agent_data:
            return False
        if not isinstance(agent_data["accounts"], list):
            return False

        for acc in agent_data["accounts"]:
            if not isinstance(acc, dict):
                return False
            for field in ["id", "label", "provider", "source", "health", "native_window", "weekly_window", "free_trial_invites"]:
                if field not in acc:
                    return False

            if "isActive" in acc and not isinstance(acc["isActive"], bool):
                return False
            if "token_history" in acc and not isinstance(acc["token_history"], dict):
                return False

            ww = acc.get("weekly_window")
            if not isinstance(ww, dict):
                return False
            if "usage_percentage" not in ww or not isinstance(ww["usage_percentage"], (int, float)):
                return False
            if ww.get("total_capacity") is not None and not isinstance(ww["total_capacity"], int):
                return False
            if ww.get("available_capacity") is not None and not isinstance(ww["available_capacity"], int):
                return False

    return True
