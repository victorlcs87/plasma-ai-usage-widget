"""Core collector engine coordinating config, discovery, and canonical status generation."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from ai_usage_collector.config import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CONFIG_PATH,
    ensure_secure_dir,
    ensure_secure_file,
    get_accounts_for_agent,
    load_config,
    save_secure_json,
)
from ai_usage_collector.contract import (
    build_agent_account_status,
    build_empty_status_contract,
    get_current_iso_timestamp,
)
from ai_usage_collector.discovery import discover_account
from ai_usage_collector.extractors.claude import extract_claude_status


def save_status_cache(status_data: dict[str, Any], path: str | Path | None = None) -> Path:
    """Save status.json payload atomically with secure permissions (0600)."""
    file_path = Path(path).expanduser().resolve() if path else DEFAULT_CACHE_PATH
    return save_secure_json(status_data, file_path, prefix="status_")


def load_status_cache(path: str | Path | None = None) -> dict[str, Any] | None:
    """Load cached status.json if exists."""
    file_path = Path(path).expanduser().resolve() if path else DEFAULT_CACHE_PATH
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_and_save(
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute on-demand collection and write canonical status.json."""
    config = load_config(config_path)
    now_dt = now or datetime.now(timezone.utc)
    status_payload = build_empty_status_contract(now_iso=now_dt.isoformat())

    agents_to_collect = ["claude", "codex", "gemini"]

    for agent_id in agents_to_collect:
        accounts = get_accounts_for_agent(config, agent_id)
        account_statuses: list[dict[str, Any]] = []

        agent_has_valid_account = False

        for acc in accounts:
            acc_id = acc.get("id", "default")
            label = acc.get("label", f"{agent_id.capitalize()} ({acc_id})")
            source = acc.get("source", "auto")
            cred_path = acc.get("credential_path")
            manual_invite = acc.get("manual_invite_url")

            health = discover_account(agent_id, cred_path)
            native_window = None
            weekly_window = None
            invites = None

            if agent_id == "claude":
                claude_data = extract_claude_status(acc, initial_health=health, now=now_dt)
                health = claude_data.get("health", health)
                native_window = claude_data.get("native_window")
                weekly_window = claude_data.get("weekly_window")
                invites = claude_data.get("free_trial_invites")

            if health.get("status") == "valid":
                agent_has_valid_account = True
                # If label was generic and user identity or subscription was discovered, enrich label display
                meta = health.get("metadata", {})
                if label.endswith("(Padrão)"):
                    if meta.get("email"):
                        label = f"{agent_id.capitalize()} ({meta['email']})"
                    elif meta.get("subscription_type"):
                        label = f"{agent_id.capitalize()} ({meta['subscription_type'].capitalize()})"

            acc_status = build_agent_account_status(
                provider=agent_id,
                account_id=acc_id,
                label=label,
                source=source,
                health=health,
                manual_invite_url=manual_invite,
                native_window=native_window,
                weekly_window=weekly_window,
                free_trial_invites=invites,
            )
            account_statuses.append(acc_status)

        status_payload["agents"][agent_id]["accounts"] = account_statuses
        if account_statuses:
            if agent_has_valid_account:
                status_payload["agents"][agent_id]["status"] = "ok"
            else:
                # Check if all missing or error
                all_missing = all(
                    a["health"].get("status") == "missing_credentials" for a in account_statuses
                )
                if all_missing:
                    status_payload["agents"][agent_id]["status"] = "missing_credentials"
                else:
                    status_payload["agents"][agent_id]["status"] = "warning"
        else:
            status_payload["agents"][agent_id]["status"] = "not_configured"

    # Save to disk
    save_status_cache(status_payload, cache_path)
    return status_payload
