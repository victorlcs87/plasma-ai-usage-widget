"""Native extractor for Google Gemini / Antigravity CLI local artifacts."""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ai_usage_collector import refresh
from ai_usage_collector.config import save_secure_json
from ai_usage_collector.contract import parse_window_seconds, window_type_from_seconds
from ai_usage_collector.discovery import (
    discover_gemini,
    extract_jwt_identity,
)

# Fallback of the local heuristic only; the quota summary reports the real Native Window duration
GEMINI_DAILY_SECONDS = 24 * 3600  # 86400s
GEMINI_5H_SECONDS = 5 * 3600  # 18000s, duration of the "gemini-5h" quota bucket
GEMINI_7D_SECONDS = 7 * 86400  # 604800s

DEFAULT_GEMINI_CAPACITY_BY_TIER: dict[str, int] = {
    "free": 50,
    "pro": 100,
    "ultra": 200,
    "enterprise": 500,
    "default": 100,
}
DEFAULT_GEMINI_FALLBACK_CAPACITY = 100


_MAX_EPOCH_MS = 253402300799 * 1000  # 9999-12-31 in ms


def parse_timestamp(ts: Any) -> float | None:
    """Parse various timestamp formats into UTC epoch seconds."""
    if ts is None:
        return None

    if isinstance(ts, (int, float)):
        # If timestamp is in milliseconds (greater than ~1973 in seconds)
        # Non-finite or beyond year 9999 would overflow datetime.fromtimestamp: treat as unknown
        if not (0 < ts <= _MAX_EPOCH_MS):
            return None
        return float(ts) / 1000.0 if ts > 1e11 else float(ts)

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


def get_gemini_keyring_raw(timeout: float = 3.0) -> dict[str, Any] | None:
    """Retrieve full raw Gemini credentials from system keyring via secret-tool."""
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", "service", "gemini", "username", "antigravity"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None

        raw = proc.stdout.strip()
        if not raw:
            return None

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        return {"access_token": raw, "token_type": "Bearer"}
    except Exception:
        return None


def get_gemini_keyring_token(timeout: float = 3.0) -> str | None:
    """Retrieve Gemini OAuth access token from system keyring via secret-tool."""
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", "service", "gemini", "username", "antigravity"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode == 0:
            raw = proc.stdout.strip()
            if not raw:
                return None
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    tok = data.get("token")
                    if isinstance(tok, dict) and tok.get("access_token"):
                        return str(tok["access_token"])
                    if isinstance(tok, str) and tok:
                        return tok
                    if data.get("access_token"):
                        return str(data["access_token"])
            except Exception:
                pass
            return raw
    except Exception:
        pass
    return None


def sync_gemini_keyring_to_file(keyring_data: dict[str, Any], cred_file: Path) -> bool:
    """Synchronize active keyring credentials to oauth_creds.json with 0600 permissions."""
    try:
        file_data: dict[str, Any] = {}
        if cred_file.exists():
            try:
                with open(cred_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        file_data = loaded
            except Exception:
                file_data = {}

        tok_dict = keyring_data.get("token") if isinstance(keyring_data.get("token"), dict) else {}
        access_token = (
            tok_dict.get("access_token")
            or keyring_data.get("access_token")
            or file_data.get("access_token")
        )
        refresh_token = (
            tok_dict.get("refresh_token")
            or keyring_data.get("refresh_token")
            or file_data.get("refresh_token")
        )
        token_type = (
            tok_dict.get("token_type")
            or keyring_data.get("token_type")
            or file_data.get("token_type", "Bearer")
        )
        id_token = (
            keyring_data.get("id_token")
            or tok_dict.get("id_token")
            or file_data.get("id_token")
        )
        expiry_val = tok_dict.get("expiry") or keyring_data.get("expiry_date") or keyring_data.get("expiry")

        sync_payload = dict(file_data)
        if access_token:
            sync_payload["access_token"] = access_token
        if refresh_token:
            sync_payload["refresh_token"] = refresh_token
        if token_type:
            sync_payload["token_type"] = token_type
        if id_token:
            sync_payload["id_token"] = id_token
        if "scope" not in sync_payload and keyring_data.get("scope"):
            sync_payload["scope"] = keyring_data["scope"]
        elif "scope" not in sync_payload:
            sync_payload["scope"] = "openid https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email"

        if expiry_val:
            exp_ts = parse_timestamp(expiry_val)
            if exp_ts is not None:
                sync_payload["expiry_date"] = int(exp_ts * 1000)
            elif isinstance(expiry_val, (int, float)):
                sync_payload["expiry_date"] = int(expiry_val if expiry_val > 1e11 else expiry_val * 1000)

        save_secure_json(sync_payload, cred_file, prefix="gemini_oauth_")
        return True
    except Exception:
        return False


def fetch_gemini_quota_api(
    token: str,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Fetch official quota summary from Google Cloud Code internal API."""
    if not token:
        return None
    url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity",
        },
        method="POST",
    )
    return refresh.fetch_json(
        "gemini", token, req, timeout, valid=lambda d: any(parse_gemini_quota_buckets(d))
    )


def parse_gemini_quota_buckets(
    data: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Extract gemini-5h and gemini-weekly quota bucket entries from API response."""
    bucket_5h: dict[str, Any] | None = None
    bucket_weekly: dict[str, Any] | None = None

    if not isinstance(data, dict):
        if isinstance(data, list):
            data = {"buckets": data}
        else:
            return None, None

    # 1. Direct dictionary keys
    for k in ["gemini-5h", "5h"]:
        if isinstance(data.get(k), dict):
            bucket_5h = data[k]
            break
    for k in ["gemini-weekly", "weekly", "7d", "seven_day"]:
        if isinstance(data.get(k), dict):
            bucket_weekly = data[k]
            break

    # 2. Check "groups" structure from Google Cloud Code API
    groups = data.get("groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_buckets = group.get("buckets")
            if not isinstance(group_buckets, list):
                continue
            is_gemini_group = "gemini" in str(group.get("displayName", "")).lower()
            for b in group_buckets:
                if not isinstance(b, dict):
                    continue
                bid = str(b.get("bucketId") or b.get("name") or b.get("id") or "").lower()
                win = str(b.get("window") or "").lower()
                if bid == "gemini-5h" or (not bucket_5h and win == "5h" and is_gemini_group):
                    bucket_5h = b
                elif bid == "gemini-weekly" or (not bucket_weekly and win in ("weekly", "7d") and is_gemini_group):
                    bucket_weekly = b

    # 3. Lists in known wrapper keys
    candidate_lists: list[list[Any]] = []
    for list_key in ["buckets", "quotas", "userQuotas", "quotaSummaries"]:
        val = data.get(list_key)
        if isinstance(val, list):
            candidate_lists.append(val)

    for lst in candidate_lists:
        for item in lst:
            if not isinstance(item, dict):
                continue
            name = str(item.get("bucketId") or item.get("name") or item.get("id") or item.get("window") or "").lower()
            if not bucket_5h and ("gemini-5h" in name or name == "5h" or "5h" in name):
                bucket_5h = item
            if not bucket_weekly and ("gemini-weekly" in name or name in ("weekly", "7d") or "weekly" in name or "7d" in name):
                bucket_weekly = item

    return bucket_5h, bucket_weekly


def parse_gemini_model_quotas(data: Any) -> list[dict[str, Any]]:
    """Per-model quota entries from the quota summary, one per (model, window).

    ASSUMPTION: the real per-model payload is undocumented. Buckets carrying a model name under
    "modelId"/"model"/"modelName"/"displayName" are taken as per-model, with the same shape as the
    aggregate buckets (bucketId/window, remainingFraction, resetTime). Adjust if a real sample differs.
    usage_percentage is None when remainingFraction is missing, non-finite or outside [0, 1]:
    never a fake 0%.
    """
    if not isinstance(data, dict):
        return []
    buckets: list[Any] = []
    for key in ("buckets", "quotas", "userQuotas", "quotaSummaries"):
        if isinstance(data.get(key), list):
            buckets += data[key]
    for group in data.get("groups") if isinstance(data.get("groups"), list) else []:
        if isinstance(group, dict) and isinstance(group.get("buckets"), list):
            buckets += group["buckets"]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for b in buckets:
        if not isinstance(b, dict):
            continue
        model = next((b[k] for k in ("modelId", "model", "modelName", "displayName") if isinstance(b.get(k), str) and b[k]), None)
        window = b.get("window") if isinstance(b.get("window"), str) and b["window"] else None
        if model is None or (model, window) in seen:
            continue
        seen.add((model, window))
        rem = b.get("remainingFraction")
        pct = None
        if isinstance(rem, (int, float)) and not isinstance(rem, bool) and math.isfinite(rem) and 0 <= rem <= 1:
            pct = round((1.0 - float(rem)) * 100.0, 1)
        reset = parse_timestamp(b.get("resetTime") or b.get("resets_at"))
        out.append({
            "model": model,
            "window": window,
            "usage_percentage": pct,
            "reset_time": datetime.fromtimestamp(reset, tz=timezone.utc).isoformat() if reset is not None else None,
        })
    return out


def gemini_bucket_seconds(bucket: dict[str, Any], default: int) -> int:
    """Duration of a quota bucket from its window or id suffix ("5h", "gemini-weekly"), else default.

    The quota summary has no explicit duration field: it is deduced from the bucket name.
    """
    for key in ("window", "bucketId", "name", "id"):
        value = bucket.get(key)
        if isinstance(value, str):
            seconds = parse_window_seconds(value.rsplit("-", 1)[-1])
            if seconds:
                return seconds
    return default


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
    metadata = dict(health.get("metadata", {}))

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

    # Daily window calculations (last 24 hours) - local heuristic, overridden by the quota summary
    native_window_seconds = GEMINI_DAILY_SECONDS
    weekly_window_seconds = GEMINI_7D_SECONDS
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

    model_quotas: list[dict[str, Any]] = []

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

    # Keyring or file token lookup for official API
    file_token = None
    file_refresh_token = None
    file_expired = False
    if cred_file.exists():
        try:
            with open(cred_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            if isinstance(cdata, dict):
                file_refresh_token = cdata.get("refresh_token")
                raw_token = cdata.get("access_token")
                exp = cdata.get("expiry_date")
                if exp:
                    exp_sec = parse_timestamp(exp)
                    if exp_sec is not None and exp_sec < now_sec:
                        file_expired = True
                if raw_token and not file_expired:
                    file_token = raw_token
        except Exception:
            pass

    from ai_usage_collector.discovery import DEFAULT_GEMINI_CREDENTIALS
    default_antigravity = Path("~/.gemini/antigravity-cli").expanduser().resolve()
    default_gemini = Path("~/.gemini").expanduser().resolve()
    default_cred_path = DEFAULT_GEMINI_CREDENTIALS.expanduser().resolve()

    is_default_account = (
        account.get("id") in ("default", None)
        and "profiles" not in str(cred_path_val or "")
        and "profiles" not in str(account.get("gemini_dir") or "")
    )

    keyring_token = get_gemini_keyring_token() if is_default_account else None
    keyring_raw = get_gemini_keyring_raw() if is_default_account else None

    if file_token and not file_expired:
        token = file_token
        token_is_from_keyring = False
    elif keyring_token:
        token = keyring_token
        token_is_from_keyring = True
    elif file_token:
        token = file_token
        token_is_from_keyring = False
    else:
        token = account.get("access_token") or account.get("token")
        token_is_from_keyring = False

    weekly_total_capacity = account.get("weekly_capacity") or (total_capacity * 7)

    native_source = weekly_source = "local"  # "api" | "api_missing" | "local" (ver limit_changes.py)
    native_api_fields: list[str] = []  # fatos realmente lidos da API: "duration", "release"
    weekly_api_fields: list[str] = []

    # Attempt primary official API usage route
    api_data = None
    if token:
        api_data = fetch_gemini_quota_api(token)

    if api_data:
        # Official API responded with success! Mark valid and update message
        health["status"] = "valid"
        health["message"] = "Credencial Gemini ativa detectada via API oficial"

        # Synchronize keyring token to local file if token came from keyring,
        # but NEVER overwrite an isolated account profile
        is_isolated_profile = "profiles" in Path(cred_file).resolve().parts
        if token_is_from_keyring and not is_isolated_profile:
            sync_data = keyring_raw if (keyring_raw and isinstance(keyring_raw, dict)) else {"access_token": token}
            id_tok = (
                sync_data.get("id_token")
                or (sync_data.get("token", {}).get("id_token") if isinstance(sync_data.get("token"), dict) else None)
            )
            email = extract_jwt_identity(id_tok) if id_tok else None
            if email:
                metadata["email"] = email
            metadata["source"] = "keyring"

            sync_gemini_keyring_to_file(sync_data, cred_file)
            metadata["credential_path"] = str(cred_file)

        health["metadata"] = metadata

        bucket_5h, bucket_weekly = parse_gemini_quota_buckets(api_data)
        model_quotas = parse_gemini_model_quotas(api_data)

        has_5h = bool(bucket_5h) and bucket_5h.get("remainingFraction") is not None
        has_weekly = bool(bucket_weekly) and bucket_weekly.get("remainingFraction") is not None
        if has_5h or has_weekly:  # resposta sem nenhum bucket reconhecivel nao diz que o limite sumiu
            native_source = "api" if has_5h else "api_missing"
            weekly_source = "api" if has_weekly else "api_missing"

        # 5h window from official API
        if bucket_5h and bucket_5h.get("remainingFraction") is not None:
            rem_5h = float(bucket_5h["remainingFraction"])
            usage_percentage = round((1.0 - rem_5h) * 100.0, 1)
            available_capacity = max(0, round(total_capacity * rem_5h))
            used_daily = total_capacity - available_capacity
            native_window_seconds = gemini_bucket_seconds(bucket_5h, GEMINI_5H_SECONDS)
            if gemini_bucket_seconds(bucket_5h, 0):
                native_api_fields.append("duration")

            r_sec = parse_timestamp(bucket_5h.get("resetTime") or bucket_5h.get("resets_at"))
            if r_sec is not None:
                native_api_fields.append("release")
                release_sec = r_sec
                seconds_remaining = max(0, int(release_sec - now_sec))
                release_time = datetime.fromtimestamp(release_sec, tz=timezone.utc).isoformat()
            elif native_window_seconds != GEMINI_DAILY_SECONDS:
                # Bucket duration without a reset: the daily heuristic release would be wrong
                seconds_remaining = None
                release_time = None

        # Weekly window from official API
        if bucket_weekly and bucket_weekly.get("remainingFraction") is not None:
            rem_w = float(bucket_weekly["remainingFraction"])
            weekly_usage_percentage = round((1.0 - rem_w) * 100.0, 1)
            weekly_available_capacity = max(0, round(weekly_total_capacity * rem_w))
            weekly_used_capacity = weekly_total_capacity - weekly_available_capacity
            weekly_window_seconds = gemini_bucket_seconds(bucket_weekly, GEMINI_7D_SECONDS)
            if gemini_bucket_seconds(bucket_weekly, 0):
                weekly_api_fields.append("duration")

            w_sec = parse_timestamp(bucket_weekly.get("resetTime") or bucket_weekly.get("resets_at"))
            if w_sec is not None:
                weekly_api_fields.append("release")
                cycle_reset_sec = w_sec
                weekly_seconds_remaining = max(0, int(cycle_reset_sec - now_sec))
                cycle_reset_time = datetime.fromtimestamp(cycle_reset_sec, tz=timezone.utc).isoformat()
            elif weekly_window_seconds != GEMINI_7D_SECONDS:
                weekly_seconds_remaining = None
                cycle_reset_time = None
        else:
            weekly_usage_percentage = min(100.0, round((used_7d / weekly_total_capacity) * 100.0, 1)) if weekly_total_capacity > 0 else 0.0
            weekly_available_capacity = max(0, weekly_total_capacity - used_7d)
            weekly_used_capacity = used_7d
    else:
        # Fallback local calculation
        # Only mark session_expired if access_token is expired AND no refresh token AND no keyring token
        expiry_date = metadata.get("expiry_date")
        has_refresh = bool(file_refresh_token or (keyring_raw and (keyring_raw.get("refresh_token") or (isinstance(keyring_raw.get("token"), dict) and keyring_raw["token"].get("refresh_token")))) or metadata.get("renewable"))
        has_keyring_token = bool(keyring_token)

        is_token_expired = False
        if expiry_date:
            exp_sec = parse_timestamp(expiry_date)
            if exp_sec is not None and exp_sec < now_sec:
                is_token_expired = True

        if is_token_expired and not has_refresh and not has_keyring_token:
            health = {
                "status": "session_expired",
                "message": "Sessão Gemini expirada. Reautenticação necessária.",
                "detected": True,
                "metadata": metadata,
            }

        weekly_usage_percentage = min(100.0, round((used_7d / weekly_total_capacity) * 100.0, 1)) if weekly_total_capacity > 0 else 0.0
        weekly_available_capacity = max(0, weekly_total_capacity - used_7d)
        weekly_used_capacity = used_7d

    native_window = {
        "type": window_type_from_seconds(native_window_seconds),
        "source": native_source,
        "api_fields": native_api_fields,
        "window_seconds": native_window_seconds,
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
        "total_capacity": weekly_total_capacity,
        "used_capacity": weekly_used_capacity,
        "available_capacity": weekly_available_capacity,
        "usage_percentage": weekly_usage_percentage,
        "messages_used": used_7d,
        "tokens_used": 0,
        "source": weekly_source,
        "api_fields": weekly_api_fields,
        "cycle_reset_time": cycle_reset_time,
        "seconds_remaining": weekly_seconds_remaining,
        "window_seconds": weekly_window_seconds,
    }

    result = {
        "health": health,
        "native_window": native_window,
        "weekly_window": weekly_window,
        "free_trial_invites": invites,
    }
    if model_quotas:
        result["usage_details"] = {"quota_by_model": model_quotas}
    return result
