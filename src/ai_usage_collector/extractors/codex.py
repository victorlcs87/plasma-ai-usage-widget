"""Native extractor for OpenAI Codex CLI local artifacts."""

from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ai_usage_collector import refresh
from ai_usage_collector.discovery import discover_codex

CODEX_3H_SECONDS = 3 * 3600  # 10800s
CODEX_7D_SECONDS = 7 * 86400  # 604800s

DEFAULT_CODEX_CAPACITY_BY_TIER: dict[str, int] = {
    "free": 20,
    "plus": 50,
    "team": 100,
    "enterprise": 200,
    "chatgpt": 50,
    "pro": 100,
}
DEFAULT_CODEX_FALLBACK_CAPACITY = 50


def parse_timestamp(ts: Any) -> float | None:
    """Parse various timestamp formats into UTC epoch seconds."""
    if ts is None:
        return None

    if isinstance(ts, (int, float)):
        # If timestamp is in milliseconds (greater than ~1973 in seconds)
        if ts > 1e11:
            return float(ts) / 1000.0
        if ts > 0:
            return float(ts)
        return None

    if isinstance(ts, str):
        ts = ts.strip()
        if not ts:
            return None
        # Try float conversion
        try:
            val = float(ts)
            return parse_timestamp(val)
        except ValueError:
            pass

        # Try ISO 8601 string or SQLite datetime
        try:
            clean_ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass

        # Try standard SQL datetime format if timezone missing
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                pass

    return None


def read_codex_sqlite_timestamps(db_path: Path) -> list[float]:
    """Extract interaction timestamps from Codex thread_history_1.sqlite."""
    timestamps: list[float] = []
    if not db_path.exists():
        return timestamps

    try:
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            cursor = conn.cursor()

            # Check existing tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            if "thread_turns" in tables:
                try:
                    cursor.execute(
                        "SELECT started_at, completed_at FROM thread_turns WHERE started_at IS NOT NULL"
                    )
                    for started_at, completed_at in cursor.fetchall():
                        ts = parse_timestamp(started_at) or parse_timestamp(completed_at)
                        if ts is not None:
                            timestamps.append(ts)
                except sqlite3.Error:
                    pass

            if "thread_items" in tables:
                try:
                    cursor.execute(
                        "SELECT created_at_ms FROM thread_items WHERE item_type IN ('userMessage', 'turnContext') OR item_type != ''"
                    )
                    for (created_at_ms,) in cursor.fetchall():
                        ts = parse_timestamp(created_at_ms)
                        if ts is not None:
                            timestamps.append(ts)
                except sqlite3.Error:
                    pass
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        return []

    return timestamps


def read_codex_logs_timestamps(logs_db_path: Path) -> list[float]:
    """Extract timestamps from Codex logs_2.sqlite."""
    timestamps: list[float] = []
    if not logs_db_path.exists():
        return timestamps

    try:
        uri = f"file:{logs_db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs'")
            if cursor.fetchone():
                cursor.execute(
                    "SELECT ts FROM logs WHERE (target LIKE '%session%' OR target LIKE '%thread%' OR feedback_log_body LIKE '%thread%') AND ts IS NOT NULL"
                )
                for (ts_val,) in cursor.fetchall():
                    ts = parse_timestamp(ts_val)
                    if ts is not None:
                        timestamps.append(ts)
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        return []

    return timestamps


def read_codex_history_timestamps(history_path: Path) -> list[float]:
    """Read prompt timestamps from Codex history.jsonl file."""
    timestamps: list[float] = []
    if not history_path.exists():
        return timestamps

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    raw_ts = entry.get("ts") or entry.get("timestamp")
                    parsed = parse_timestamp(raw_ts)
                    if parsed is not None:
                        timestamps.append(parsed)
                except Exception:
                    continue
    except Exception:
        return []

    return timestamps


def extract_codex_invites(
    codex_dir: Path,
    manual_invite_url: str | None = None,
    manual_invite_count: int | None = None,
) -> dict[str, Any]:
    """Extract free trial invites from local files or fallback to config."""
    extracted_url: str | None = None
    extracted_count: int | None = None

    search_files = [
        codex_dir / "auth.json",
        codex_dir / "config.toml",
        codex_dir / "settings.json",
    ]
    for sf in search_files:
        if sf.exists() and sf.suffix == ".json":
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for key in ["referralUrl", "inviteUrl", "freeTrialUrl", "trialUrl"]:
                        if key in data and isinstance(data[key], str) and data[key].strip():
                            extracted_url = data[key].strip()
                            break
                    for count_key in ["invitesAvailable", "invitesCount", "availableInvites"]:
                        if count_key in data and isinstance(data[count_key], int):
                            extracted_count = data[count_key]
                            break
            except Exception:
                pass
        if extracted_url:
            break

    final_url = extracted_url or manual_invite_url
    if manual_invite_count is not None:
        final_count = manual_invite_count
    elif extracted_count is not None:
        final_count = extracted_count
    else:
        final_count = 1 if final_url else 0

    return {
        "available_count": final_count,
        "invite_url": final_url,
    }


def resolve_codex_capacity(account: dict[str, Any], health: dict[str, Any]) -> int:
    """Resolve total capacity for 3h window based on config or account metadata."""
    for key in ["rate_limit_capacity", "capacity_limit", "quota_limit"]:
        val = account.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)

    metadata = health.get("metadata", {})
    auth_mode = str(metadata.get("auth_mode", "")).lower()
    sub_type = str(metadata.get("subscription_type", "")).lower()

    if sub_type in DEFAULT_CODEX_CAPACITY_BY_TIER:
        return DEFAULT_CODEX_CAPACITY_BY_TIER[sub_type]
    if auth_mode in DEFAULT_CODEX_CAPACITY_BY_TIER:
        return DEFAULT_CODEX_CAPACITY_BY_TIER[auth_mode]

    return DEFAULT_CODEX_FALLBACK_CAPACITY


def deduplicate_timestamps(raw_timestamps: list[float], tolerance_sec: float = 1.0) -> list[float]:
    """Deduplicate timestamps within a small tolerance window."""
    if not raw_timestamps:
        return []
    sorted_ts = sorted(raw_timestamps)
    deduped: list[float] = [sorted_ts[0]]
    for ts in sorted_ts[1:]:
        if (ts - deduped[-1]) >= tolerance_sec:
            deduped.append(ts)
    return deduped


def fetch_codex_usage_api(
    access_token: str,
    account_id: str | None = None,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Fetch official usage metrics from OpenAI ChatGPT backend WHAM API."""
    if not access_token:
        return None
    url = "https://chatgpt.com/backend-api/wham/usage"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "codex-cli",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    req = urllib.request.Request(url, headers=headers, method="GET")
    return refresh.fetch_json("codex", f"{access_token}|{account_id or ''}", req, timeout)


def parse_codex_credits(api_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map the optional credits block of wham/usage ({has_credits, unlimited, balance})."""
    credits = (api_data or {}).get("credits")
    if not isinstance(credits, dict):
        return None
    if credits.get("unlimited") is True:
        return {"unlimited": True}
    if not credits.get("has_credits"):
        return None
    try:
        return {"unlimited": False, "balance": float(credits.get("balance"))}
    except (TypeError, ValueError):
        return None


def read_codex_current_model(codex_dir: Path) -> str | None:
    """Model of the latest session turn (sessions rollout), else the `model` key of config.toml."""
    rollouts = glob.glob(str(codex_dir / "sessions" / "*" / "*" / "*" / "rollout-*.jsonl"))
    if rollouts:
        try:
            latest = max(rollouts, key=os.path.getmtime)
            model = None
            with open(latest, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"turn_context"' not in line:
                        continue
                    try:
                        payload = json.loads(line).get("payload") or {}
                    except ValueError:
                        continue
                    if isinstance(payload.get("model"), str) and payload["model"]:
                        model = payload["model"]
            if model:
                return model
        except OSError:
            pass
    try:
        config_text = (codex_dir / "config.toml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # ponytail: top-level `model = "..."` via regex (tomllib needs 3.11); profiles ignored
    match = re.search(r'^model\s*=\s*["\']([^"\']+)["\']', config_text, re.MULTILINE)
    return match.group(1) if match else None


def extract_codex_status(
    account: dict[str, Any],
    initial_health: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extract metrics, calculate 3h and weekly windows, and format Codex status."""
    now_dt = now or datetime.now(timezone.utc)
    now_sec = now_dt.timestamp()

    # Determine codex directory
    cred_path_val = account.get("credential_path")
    if account.get("codex_dir"):
        codex_dir = Path(account["codex_dir"]).expanduser().resolve()
    elif cred_path_val:
        p = Path(cred_path_val).expanduser().resolve()
        codex_dir = p.parent if p.is_file() or p.suffix == ".json" else p
    else:
        codex_dir = Path("~/.codex").expanduser().resolve()

    cred_file = (
        Path(cred_path_val).expanduser().resolve()
        if cred_path_val
        else (codex_dir / "auth.json")
    )

    # Health check
    health = initial_health or discover_codex(cred_file)

    # Free trial invites
    invites = extract_codex_invites(
        codex_dir=codex_dir,
        manual_invite_url=account.get("manual_invite_url"),
        manual_invite_count=account.get("manual_invite_count"),
    )

    # Capacity
    total_capacity = resolve_codex_capacity(account, health)

    # Collect timestamps across sqlite and history
    raw_timestamps: list[float] = []

    sqlite_db = codex_dir / "thread_history_1.sqlite"
    raw_timestamps.extend(read_codex_sqlite_timestamps(sqlite_db))

    history_file = codex_dir / "history.jsonl"
    raw_timestamps.extend(read_codex_history_timestamps(history_file))

    # If no timestamps found yet, fallback to logs_2.sqlite
    if not raw_timestamps:
        logs_db = codex_dir / "logs_2.sqlite"
        raw_timestamps.extend(read_codex_logs_timestamps(logs_db))

    all_timestamps = deduplicate_timestamps(raw_timestamps)

    # 3-hour window calculations
    start_3h_sec = now_sec - CODEX_3H_SECONDS
    in_3h_ts = [t for t in all_timestamps if start_3h_sec <= t <= now_sec]
    used_3h = len(in_3h_ts)

    available_capacity = max(0, total_capacity - used_3h)
    usage_percentage = (
        min(100.0, round((used_3h / total_capacity) * 100.0, 1))
        if total_capacity > 0
        else 0.0
    )

    if in_3h_ts:
        oldest_3h_sec = min(in_3h_ts)
        release_sec = oldest_3h_sec + CODEX_3H_SECONDS
        seconds_remaining = max(0, int(release_sec - now_sec))
        release_time = datetime.fromtimestamp(release_sec, tz=timezone.utc).isoformat()
    else:
        release_time = None
        seconds_remaining = None

    # Weekly window calculations (last 7 days)
    start_7d_sec = now_sec - CODEX_7D_SECONDS
    in_7d_ts = [t for t in all_timestamps if start_7d_sec <= t <= now_sec]
    used_7d = len(in_7d_ts)

    if in_7d_ts:
        oldest_7d_sec = min(in_7d_ts)
        cycle_reset_sec = oldest_7d_sec + CODEX_7D_SECONDS
        weekly_seconds_remaining = max(0, int(cycle_reset_sec - now_sec))
        cycle_reset_time = datetime.fromtimestamp(cycle_reset_sec, tz=timezone.utc).isoformat()
    else:
        cycle_reset_time = None
        weekly_seconds_remaining = None

    # Read access token and account id for official API
    access_token = None
    account_id = None
    if cred_file.exists():
        try:
            with open(cred_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            if isinstance(cdata, dict):
                toks = cdata.get("tokens")
                if isinstance(toks, dict):
                    access_token = toks.get("access_token")
                    account_id = toks.get("account_id") or toks.get("ChatGPT-Account-Id")
                if not access_token:
                    access_token = cdata.get("access_token")
                if not account_id:
                    account_id = cdata.get("account_id") or cdata.get("ChatGPT-Account-Id")
        except Exception:
            pass
    if not access_token:
        access_token = account.get("access_token") or account.get("token")
    if not account_id:
        account_id = account.get("account_id") or account.get("chatgpt_account_id")

    weekly_total_capacity = account.get("weekly_capacity") or (total_capacity * 7)

    # Attempt primary official API usage route
    api_data = None
    if access_token and health.get("status") == "valid":
        api_data = fetch_codex_usage_api(access_token, account_id)

    if api_data and (isinstance(api_data.get("rate_limit"), dict) or "primary_window" in api_data):
        rate_limit = api_data.get("rate_limit") or api_data
        primary = rate_limit.get("primary_window") or {}
        secondary = rate_limit.get("secondary_window") or {}

        # Primary window (active window)
        used_pct_primary = primary.get("used_percent")
        if used_pct_primary is not None:
            usage_percentage = round(float(used_pct_primary), 1)
            used_3h = round(total_capacity * (usage_percentage / 100.0))
            available_capacity = max(0, total_capacity - used_3h)

        resets_at_primary = primary.get("reset_at")
        if resets_at_primary:
            r_sec = parse_timestamp(resets_at_primary)
            if r_sec is not None:
                release_sec = r_sec
                seconds_remaining = max(0, int(release_sec - now_sec))
                release_time = datetime.fromtimestamp(release_sec, tz=timezone.utc).isoformat()

        # Secondary window (weekly window)
        used_pct_secondary = secondary.get("used_percent")
        if used_pct_secondary is not None:
            weekly_usage_percentage = round(float(used_pct_secondary), 1)
            weekly_used_capacity = round(weekly_total_capacity * (weekly_usage_percentage / 100.0))
            weekly_available_capacity = max(0, weekly_total_capacity - weekly_used_capacity)
        else:
            weekly_usage_percentage = min(100.0, round((used_7d / weekly_total_capacity) * 100.0, 1)) if weekly_total_capacity > 0 else 0.0
            weekly_available_capacity = max(0, weekly_total_capacity - used_7d)
            weekly_used_capacity = used_7d

        resets_at_secondary = secondary.get("reset_at")
        if resets_at_secondary:
            w_sec = parse_timestamp(resets_at_secondary)
            if w_sec is not None:
                cycle_reset_sec = w_sec
                weekly_seconds_remaining = max(0, int(cycle_reset_sec - now_sec))
                cycle_reset_time = datetime.fromtimestamp(cycle_reset_sec, tz=timezone.utc).isoformat()

        # Promo / invite mapping
        promo = api_data.get("promo")
        if promo:
            if isinstance(promo, dict):
                p_url = promo.get("invite_url") or promo.get("referral_url") or promo.get("url")
                p_cnt = promo.get("available_count") or promo.get("count")
                if p_url and not invites.get("invite_url"):
                    invites["invite_url"] = p_url
                if p_cnt is not None and account.get("manual_invite_count") is None:
                    invites["available_count"] = p_cnt
            elif isinstance(promo, str) and promo.strip() and not invites.get("invite_url"):
                invites["invite_url"] = promo.strip()
    else:
        # Fallback local calculation
        weekly_usage_percentage = min(100.0, round((used_7d / weekly_total_capacity) * 100.0, 1)) if weekly_total_capacity > 0 else 0.0
        weekly_available_capacity = max(0, weekly_total_capacity - used_7d)
        weekly_used_capacity = used_7d

    native_window = {
        "type": "3h",
        "total_capacity": total_capacity,
        "used_capacity": used_3h,
        "available_capacity": available_capacity,
        "usage_percentage": usage_percentage,
        "release_time": release_time,
        "seconds_remaining": seconds_remaining,
        "messages_used": used_3h,
        "tokens_used": 0,
    }

    weekly_window = {
        "total_tokens_or_turns": None,
        "total_capacity": weekly_total_capacity,
        "used_capacity": weekly_used_capacity,
        "available_capacity": weekly_available_capacity,
        "usage_percentage": weekly_usage_percentage,
        "messages_used": used_7d,
        "tokens_used": 0,
        "cycle_reset_time": cycle_reset_time,
        "seconds_remaining": weekly_seconds_remaining,
    }

    usage_details: dict[str, Any] = {}
    credits = parse_codex_credits(api_data)
    if credits:
        usage_details["credits"] = credits
    current_model = read_codex_current_model(codex_dir)
    if current_model:
        usage_details["current_model"] = current_model

    result = {
        "health": health,
        "native_window": native_window,
        "weekly_window": weekly_window,
        "free_trial_invites": invites,
    }
    if usage_details:
        result["usage_details"] = usage_details
    return result
