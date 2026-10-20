"""Canonical status.json data contract definitions and validations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AGENT_NATIVE_WINDOWS: dict[str, str] = {
    "claude": "5h",
    "codex": "3h",
    "gemini": "daily",
}

AGENT_NAMES: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
}


def get_current_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def build_empty_status_contract(now_iso: str | None = None) -> dict[str, Any]:
    """Construct an initial or empty canonical status.json payload."""
    timestamp = now_iso or get_current_iso_timestamp()
    return {
        "version": 1,
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
    }
    if native_window:
        default_native_window.update(native_window)

    default_weekly_window: dict[str, Any] = {
        "total_tokens_or_turns": None,
        "total_capacity": None,
        "used_capacity": None,
        "available_capacity": None,
        "usage_percentage": 0.0,
        "cycle_reset_time": None,
        "seconds_remaining": None,
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

    return {
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


def validate_status_contract(data: Any) -> bool:
    """Validate that data conforms to canonical status contract specification."""
    if not isinstance(data, dict):
        return False

    if data.get("version") != 1:
        return False

    if not isinstance(data.get("last_updated"), str):
        return False

    if not isinstance(data.get("status"), str):
        return False

    agents = data.get("agents")
    if not isinstance(agents, dict):
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
