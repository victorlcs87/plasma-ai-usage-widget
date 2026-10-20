"""Native extractor for Google Gemini / Antigravity CLI local artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
from typing import Any

from ai_usage_collector.discovery import discover_gemini

GEMINI_DAILY_SECONDS = 24 * 3600  # 86400s
GEMINI_7D_SECONDS = 7 * 86400  # 604800s

DEFAULT_GEMINI_CAPACITY_BY_TIER: dict[str, int] = {
    "free": 50,
    "pro": 100,
    "ultra": 200,
    "enterprise": 500,
    "default": 100,
}
DEFAULT_GEMINI_FALLBACK_CAPACITY = 100


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
        if not ts or ts.startswith("0001"):
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


def read_gemini_sqlite_summaries(db_path: Path) -> tuple[list[float], int]:
    """Extract interaction timestamps and total turns from conversation_summaries.db."""
    timestamps: list[float] = []
    total_steps = 0
    if not db_path.exists():
        return timestamps, total_steps

    try:
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_summaries'")
            if cursor.fetchone():
                cursor.execute(
                    "SELECT step_count, last_modified_time, last_user_input_time FROM conversation_summaries"
                )
                for step_count, last_modified, last_user_input in cursor.fetchall():
                    if isinstance(step_count, int):
                        total_steps += max(0, step_count)
                    ts = parse_timestamp(last_user_input) or parse_timestamp(last_modified)
                    if ts is not None:
                        timestamps.append(ts)
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        return [], 0

    return timestamps, total_steps


def read_gemini_history_timestamps(history_path: Path) -> list[float]:
    """Read prompt timestamps from Gemini history.jsonl file."""
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
                    raw_ts = entry.get("timestamp") or entry.get("ts")
                    parsed = parse_timestamp(raw_ts)
                    if parsed is not None:
                        timestamps.append(parsed)
                except Exception:
                    continue
    except Exception:
        return []

    return timestamps


def extract_gemini_invites(
    gemini_dir: Path,
    manual_invite_url: str | None = None,
    manual_invite_count: int | None = None,
) -> dict[str, Any]:
    """Extract free trial invites from local files or fallback to config."""
    extracted_url: str | None = None
    extracted_count: int | None = None

    search_files = [
        gemini_dir / "settings.json",
        gemini_dir / "google_accounts.json",
        gemini_dir / "oauth_creds.json",
        gemini_dir.parent / "settings.json",
        gemini_dir.parent / "google_accounts.json",
        gemini_dir.parent / "oauth_creds.json",
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


def resolve_gemini_capacity(account: dict[str, Any], health: dict[str, Any]) -> int:
    """Resolve total capacity for daily window based on config or account metadata."""
    for key in ["rate_limit_capacity", "capacity_limit", "quota_limit"]:
        val = account.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)

    metadata = health.get("metadata", {})
    sub_type = str(metadata.get("subscription_type", "")).lower()

    if sub_type in DEFAULT_GEMINI_CAPACITY_BY_TIER:
        return DEFAULT_GEMINI_CAPACITY_BY_TIER[sub_type]

    return DEFAULT_GEMINI_FALLBACK_CAPACITY


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


def extract_gemini_status(
    account: dict[str, Any],
    initial_health: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extract metrics, calculate daily and weekly windows, and format Gemini status."""
    now_dt = now or datetime.now(timezone.utc)
    now_sec = now_dt.timestamp()

    # Determine gemini directory
    cred_path_val = account.get("credential_path")
    if account.get("gemini_dir"):
        gemini_dir = Path(account["gemini_dir"]).expanduser().resolve()
    elif cred_path_val:
        p = Path(cred_path_val).expanduser().resolve()
        gemini_dir = p.parent if p.is_file() or p.suffix == ".json" else p
    else:
        default_antigravity = Path("~/.gemini/antigravity-cli").expanduser().resolve()
        default_gemini = Path("~/.gemini").expanduser().resolve()
        gemini_dir = default_antigravity if default_antigravity.exists() else default_gemini

    cred_file = (
        Path(cred_path_val).expanduser().resolve()
        if cred_path_val
        else (
            gemini_dir / "oauth_creds.json"
            if (gemini_dir / "oauth_creds.json").exists()
            else (gemini_dir.parent / "oauth_creds.json")
        )
    )

    # Health check
    health = initial_health or discover_gemini(cred_file)

    # Check expiration if available
    metadata = health.get("metadata", {})
    expiry_date = metadata.get("expiry_date")
    if expiry_date and health.get("status") == "valid":
        exp_sec = parse_timestamp(expiry_date)
        if exp_sec is not None and exp_sec < now_sec:
            # If no refresh token is present, session might be expired
            health = {
                "status": "session_expired",
                "message": "Sessão Gemini expirada. Reautenticação necessária.",
                "detected": True,
                "metadata": metadata,
            }

    # Free trial invites
    invites = extract_gemini_invites(
        gemini_dir=gemini_dir,
        manual_invite_url=account.get("manual_invite_url"),
        manual_invite_count=account.get("manual_invite_count"),
    )

    # Capacity
    total_capacity = resolve_gemini_capacity(account, health)

    # Collect timestamps across sqlite and history
    raw_timestamps: list[float] = []

    # Search for conversation_summaries.db in gemini_dir or subdirectories
    possible_dbs = [
        gemini_dir / "conversation_summaries.db",
        gemini_dir / "antigravity-cli" / "conversation_summaries.db",
    ]
    total_steps_recorded = 0
    for db_candidate in possible_dbs:
        if db_candidate.exists():
            ts_list, steps = read_gemini_sqlite_summaries(db_candidate)
            raw_timestamps.extend(ts_list)
            total_steps_recorded += steps

    # Search for history.jsonl
    possible_history = [
        gemini_dir / "history.jsonl",
        gemini_dir / "antigravity-cli" / "history.jsonl",
    ]
    for hist_candidate in possible_history:
        if hist_candidate.exists():
            raw_timestamps.extend(read_gemini_history_timestamps(hist_candidate))

    all_timestamps = deduplicate_timestamps(raw_timestamps)

    # Daily window calculations (last 24 hours)
    start_daily_sec = now_sec - GEMINI_DAILY_SECONDS
    in_daily_ts = [t for t in all_timestamps if start_daily_sec <= t <= now_sec]
    used_daily = len(in_daily_ts)

    available_capacity = max(0, total_capacity - used_daily)
    usage_percentage = (
        min(100.0, round((used_daily / total_capacity) * 100.0, 1))
        if total_capacity > 0
        else 0.0
    )

    if in_daily_ts:
        oldest_daily_sec = min(in_daily_ts)
        release_sec = oldest_daily_sec + GEMINI_DAILY_SECONDS
        seconds_remaining = max(0, int(release_sec - now_sec))
        release_time = datetime.fromtimestamp(release_sec, tz=timezone.utc).isoformat()
    else:
        release_time = None
        seconds_remaining = None

    # Weekly window calculations (last 7 days)
    start_7d_sec = now_sec - GEMINI_7D_SECONDS
    in_7d_ts = [t for t in all_timestamps if start_7d_sec <= t <= now_sec]
    used_7d = len(in_7d_ts)

    if in_7d_ts:
        oldest_7d_sec = min(in_7d_ts)
        cycle_reset_sec = oldest_7d_sec + GEMINI_7D_SECONDS
        weekly_seconds_remaining = max(0, int(cycle_reset_sec - now_sec))
        cycle_reset_time = datetime.fromtimestamp(cycle_reset_sec, tz=timezone.utc).isoformat()
    else:
        cycle_reset_time = None
        weekly_seconds_remaining = None

    native_window = {
        "type": "daily",
        "total_capacity": total_capacity,
        "used_capacity": used_daily,
        "available_capacity": available_capacity,
        "usage_percentage": usage_percentage,
        "release_time": release_time,
        "seconds_remaining": seconds_remaining,
        "messages_used": used_daily,
        "tokens_used": 0,
    }

    weekly_window = {
        "total_tokens_or_turns": total_steps_recorded if total_steps_recorded > 0 else None,
        "used_capacity": used_7d,
        "messages_used": used_7d,
        "tokens_used": 0,
        "cycle_reset_time": cycle_reset_time,
        "seconds_remaining": weekly_seconds_remaining,
    }

    return {
        "health": health,
        "native_window": native_window,
        "weekly_window": weekly_window,
        "free_trial_invites": invites,
    }
