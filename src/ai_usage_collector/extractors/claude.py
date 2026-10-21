"""Native extractor for Claude Code / Anthropic local artifacts."""

from __future__ import annotations

import glob
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ai_usage_collector.discovery import discover_claude

CLAUDE_5H_SECONDS = 5 * 3600  # 18000s
CLAUDE_7D_SECONDS = 7 * 86400  # 604800s

DEFAULT_CAPACITY_BY_TIER: dict[str, int] = {
    "free": 15,
    "pro": 45,
    "team": 100,
    "enterprise": 200,
    "default_claude_ai": 45,
}
DEFAULT_FALLBACK_CAPACITY = 45


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

        # Try ISO 8601 string
        try:
            clean_ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            return dt.timestamp()
        except Exception:
            return None

    return None


def read_history_timestamps(history_path: Path) -> list[float]:
    """Read prompt timestamps from Claude history.jsonl file."""
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
                    raw_ts = entry.get("timestamp")
                    parsed = parse_timestamp(raw_ts)
                    if parsed is not None:
                        timestamps.append(parsed)
                except Exception:
                    continue
    except Exception:
        return []

    timestamps.sort()
    return timestamps


def read_daily_activity_and_tokens(
    stats_path: Path, seven_days_ago_date: str
) -> tuple[int, int]:
    """Read aggregated 7-day activity and token usage from stats-cache.json."""
    messages = 0
    tokens = 0

    if not stats_path.exists():
        return messages, tokens

    try:
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
    except Exception:
        return messages, tokens

    if not isinstance(stats, dict):
        return messages, tokens

    # Daily activity messages
    daily_activity = stats.get("dailyActivity", [])
    if isinstance(daily_activity, list):
        for item in daily_activity:
            if isinstance(item, dict):
                dt_str = item.get("date")
                if dt_str and dt_str >= seven_days_ago_date:
                    messages += item.get("messageCount", 0)

    # Daily model tokens
    daily_tokens = stats.get("dailyModelTokens", [])
    if isinstance(daily_tokens, list):
        for item in daily_tokens:
            if isinstance(item, dict):
                dt_str = item.get("date")
                if dt_str and dt_str >= seven_days_ago_date:
                    by_model = item.get("tokensByModel", {})
                    if isinstance(by_model, dict):
                        tokens += sum(v for v in by_model.values() if isinstance(v, (int, float)))

    return messages, tokens


def scan_recent_project_tokens(
    projects_dir: Path, window_start_sec: float, now_sec: float
) -> tuple[int, int]:
    """Scan recent project session files for input/output tokens in 5h and 7d windows."""
    tokens_5h = 0
    tokens_7d = 0

    if not projects_dir.exists() or not projects_dir.is_dir():
        return tokens_5h, tokens_7d

    seven_days_ago_sec = now_sec - CLAUDE_7D_SECONDS

    try:
        pattern = str(projects_dir / "*" / "*.jsonl")
        candidates = glob.glob(pattern)
    except Exception:
        return tokens_5h, tokens_7d

    # Filter by mtime to avoid unnecessary reads, capped at 100 files
    recent_candidates = []
    for p in candidates:
        try:
            mtime = os.path.getmtime(p)
            if mtime >= seven_days_ago_sec:
                recent_candidates.append((p, mtime))
        except OSError:
            continue

    # Sort descending by mtime and limit to recent 100
    recent_candidates.sort(key=lambda x: x[1], reverse=True)
    recent_files = [x[0] for x in recent_candidates[:100]]

    for file_path in recent_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"usage"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = parse_timestamp(entry.get("timestamp"))
                        if ts is None or ts < seven_days_ago_sec:
                            continue

                        usage = entry.get("message", {}).get("usage") or entry.get("usage")
                        if not isinstance(usage, dict):
                            continue

                        in_tok = usage.get("input_tokens", 0) or 0
                        out_tok = usage.get("output_tokens", 0) or 0
                        tok_count = in_tok + out_tok

                        tokens_7d += tok_count
                        if ts >= window_start_sec:
                            tokens_5h += tok_count
                    except Exception:
                        continue
        except Exception:
            continue

    return tokens_5h, tokens_7d


def resolve_git_repo_root(cwd: str) -> str:
    """Return the main Git repository root containing cwd (worktrees map to their main repo)."""
    path = Path(cwd)
    for candidate in (path, *path.parents):
        git_entry = candidate / ".git"
        try:
            if git_entry.is_dir():
                return str(candidate)
            if git_entry.is_file():
                gitdir = git_entry.read_text(encoding="utf-8", errors="replace").strip().removeprefix("gitdir:").strip()
                if "/.git/worktrees/" in gitdir:
                    return gitdir.split("/.git/worktrees/")[0]
                return str(candidate)
        except OSError:
            continue
    return cwd


def scan_project_token_breakdown(
    projects_dir: Path, since_sec: float
) -> tuple[dict[str, int], dict[str, int]]:
    """Sum input/output tokens since since_sec by model and by Git repository (this machine only)."""
    by_model: dict[str, int] = {}
    by_project: dict[str, int] = {}
    if not projects_dir.is_dir():
        return by_model, by_project

    repo_cache: dict[str, str] = {}
    for file_path in glob.glob(str(projects_dir / "*" / "*.jsonl")):
        slug = Path(file_path).parent.name
        try:
            if os.path.getmtime(file_path) < since_sec:
                continue
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"usage"' in line:
                        _add_usage_line(line, since_sec, slug, repo_cache, by_model, by_project)
        except OSError:
            continue
    return by_model, by_project


def _add_usage_line(
    line: str,
    since_sec: float,
    slug: str,
    repo_cache: dict[str, str],
    by_model: dict[str, int],
    by_project: dict[str, int],
) -> None:
    try:
        entry = json.loads(line)
        ts = parse_timestamp(entry.get("timestamp"))
        if ts is None or ts < since_sec:
            return
        message = entry.get("message") or {}
        usage = message.get("usage") or entry.get("usage")
        if not isinstance(usage, dict):
            return
        tok = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
        if tok <= 0:
            return
        model = message.get("model")
        if isinstance(model, str) and model and model != "<synthetic>":
            by_model[model] = by_model.get(model, 0) + tok
        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd:
            if cwd not in repo_cache:
                repo_cache[cwd] = resolve_git_repo_root(cwd)
            project = Path(repo_cache[cwd]).name or slug
        else:
            project = slug
        by_project[project] = by_project.get(project, 0) + tok
    except Exception:
        return


def _sorted_breakdown(totals: dict[str, int], key: str) -> list[dict[str, Any]]:
    return [{key: k, "tokens": v} for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]


def parse_extra_usage(api_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map the optional extra_usage block of the OAuth usage API (amounts in cents) to USD."""
    extra = (api_data or {}).get("extra_usage")
    if not isinstance(extra, dict) or not extra.get("is_enabled"):
        return None
    result: dict[str, Any] = {}
    for src, dst in (("used_credits", "spent"), ("monthly_limit", "monthly_limit")):
        val = extra.get(src)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            # ponytail: assumes cents in USD, as observed in the API; adjust if a currency field appears
            result[dst] = round(val / 100.0, 2)
    if "spent" not in result:
        return None
    result["currency"] = "USD"
    return result


def extract_invites(
    claude_dir: Path,
    manual_invite_url: str | None = None,
    manual_invite_count: int | None = None,
) -> dict[str, Any]:
    """Extract free trial invites from local files or fallback to config."""
    extracted_url: str | None = None
    extracted_count: int | None = None

    # Check settings.json or credentials for invite links
    search_files = [claude_dir / "settings.json", claude_dir / ".credentials.json"]
    for sf in search_files:
        if sf.exists():
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


def resolve_tier_capacity(account: dict[str, Any], health: dict[str, Any]) -> int:
    """Resolve total capacity for 5h window based on config or account metadata."""
    # Config overrides
    for key in ["rate_limit_capacity", "capacity_limit", "quota_limit"]:
        val = account.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)

    metadata = health.get("metadata", {})
    sub_type = str(metadata.get("subscription_type", "")).lower()
    rate_tier = str(metadata.get("rate_limit_tier", "")).lower()

    if sub_type in DEFAULT_CAPACITY_BY_TIER:
        return DEFAULT_CAPACITY_BY_TIER[sub_type]
    if rate_tier in DEFAULT_CAPACITY_BY_TIER:
        return DEFAULT_CAPACITY_BY_TIER[rate_tier]

    return DEFAULT_FALLBACK_CAPACITY


def fetch_claude_usage_api(
    access_token: str,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Fetch official usage metrics from Anthropic API (https://api.anthropic.com/api/oauth/usage)."""
    if not access_token:
        return None
    url = "https://api.anthropic.com/api/oauth/usage"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "claude-code",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or (resp.getcode() if hasattr(resp, "getcode") else None)
            if status in (200, 201):
                body = resp.read()
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                data = json.loads(body)
                if isinstance(data, dict):
                    return data
    except Exception:
        return None
    return None


def extract_claude_status(
    account: dict[str, Any],
    initial_health: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extract metrics, calculate 5h and weekly windows, and format Claude status."""
    now_dt = now or datetime.now(timezone.utc)
    now_sec = now_dt.timestamp()

    # Determine claude directory
    cred_path_val = account.get("credential_path")
    if account.get("claude_dir"):
        claude_dir = Path(account["claude_dir"]).expanduser().resolve()
    elif cred_path_val:
        p = Path(cred_path_val).expanduser().resolve()
        claude_dir = p.parent if p.is_file() or p.suffix == ".json" else p
    else:
        claude_dir = Path("~/.claude").expanduser().resolve()

    cred_file = (
        Path(cred_path_val).expanduser().resolve()
        if cred_path_val
        else (claude_dir / ".credentials.json")
    )

    # Health check
    health = initial_health or discover_claude(cred_file)

    # Double check session expiration with current time
    metadata = health.get("metadata", {})
    expires_at = metadata.get("expires_at")
    if expires_at and health.get("status") == "valid":
        exp_sec = parse_timestamp(expires_at)
        if exp_sec is not None and exp_sec < now_sec:
            health = {
                "status": "session_expired",
                "message": "Sessão Claude expirada. Reautenticação necessária.",
                "detected": True,
                "metadata": metadata,
            }

    # Free trial invites
    invites = extract_invites(
        claude_dir=claude_dir,
        manual_invite_url=account.get("manual_invite_url"),
        manual_invite_count=account.get("manual_invite_count"),
    )

    # Resolve capacity limit
    total_capacity = resolve_tier_capacity(account, health)

    # Read history timestamps
    history_file = claude_dir / "history.jsonl"
    all_timestamps = read_history_timestamps(history_file)

    # 5-hour window calculations
    start_5h_sec = now_sec - CLAUDE_5H_SECONDS
    in_5h_ts = [t for t in all_timestamps if start_5h_sec <= t <= now_sec]
    used_5h = len(in_5h_ts)

    available_capacity = max(0, total_capacity - used_5h)
    usage_percentage = (
        min(100.0, round((used_5h / total_capacity) * 100.0, 1))
        if total_capacity > 0
        else 0.0
    )

    if in_5h_ts:
        oldest_5h_sec = min(in_5h_ts)
        release_sec = oldest_5h_sec + CLAUDE_5H_SECONDS
        seconds_remaining = max(0, int(release_sec - now_sec))
        release_time = datetime.fromtimestamp(release_sec, tz=timezone.utc).isoformat()
    else:
        release_time = None
        seconds_remaining = None

    # Read token usage from projects
    projects_dir = claude_dir / "projects"
    tokens_5h, project_tokens_7d = scan_recent_project_tokens(
        projects_dir, start_5h_sec, now_sec
    )

    # Weekly window calculations (last 7 days)
    start_7d_sec = now_sec - CLAUDE_7D_SECONDS
    in_7d_ts = [t for t in all_timestamps if start_7d_sec <= t <= now_sec]
    messages_7d = len(in_7d_ts)

    stats_file = claude_dir / "stats-cache.json"
    seven_days_ago_date = (now_dt - timedelta(days=7)).date().isoformat()
    cached_messages, cached_tokens = read_daily_activity_and_tokens(
        stats_file, seven_days_ago_date
    )

    total_weekly_messages = max(messages_7d, cached_messages)
    total_weekly_tokens = cached_tokens + project_tokens_7d

    if in_7d_ts:
        oldest_7d_sec = min(in_7d_ts)
        cycle_reset_sec = oldest_7d_sec + CLAUDE_7D_SECONDS
        weekly_seconds_remaining = max(0, int(cycle_reset_sec - now_sec))
        cycle_reset_time = datetime.fromtimestamp(cycle_reset_sec, tz=timezone.utc).isoformat()
    else:
        cycle_reset_time = None
        weekly_seconds_remaining = None

    # Read access token for official API
    access_token = None
    if cred_file.exists():
        try:
            with open(cred_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            if isinstance(cdata, dict):
                oauth_val = cdata.get("claudeAiOauth")
                if isinstance(oauth_val, dict) and oauth_val.get("accessToken"):
                    access_token = oauth_val["accessToken"]
                elif cdata.get("accessToken"):
                    access_token = cdata["accessToken"]
        except Exception:
            pass
    if not access_token:
        access_token = account.get("accessToken") or account.get("access_token") or account.get("token")

    weekly_total_capacity = account.get("weekly_capacity") or (total_capacity * 7)

    native_source = weekly_source = "local"  # "api" | "api_missing" | "local" (ver limit_changes.py)
    native_api_fields: list[str] = []  # fatos realmente lidos da API: "duration", "release"
    weekly_api_fields: list[str] = []

    # Attempt primary official API usage route
    api_data = None
    if access_token and health.get("status") in ("valid", "session_expired"):
        api_data = fetch_claude_usage_api(access_token)

    if api_data and (isinstance(api_data.get("five_hour"), dict) or isinstance(api_data.get("seven_day"), dict)):
        five_hour_info = api_data.get("five_hour") or {}
        seven_day_info = api_data.get("seven_day") or {}
        # five_hour nulo pode ser so ociosidade: a janela de 5h nunca vira "api_missing" (nem removida/nova);
        # a semanal sumir com a de 5h presente nao e explicavel por ociosidade.
        if five_hour_info:
            native_source = "api"
        if seven_day_info:
            weekly_source = "api"
        elif five_hour_info:
            weekly_source = "api_missing"

        # 5h window from official API
        util_5h = five_hour_info.get("utilization")
        if util_5h is not None:
            usage_percentage = round(float(util_5h), 1)
            used_5h = round(total_capacity * (usage_percentage / 100.0))
            available_capacity = max(0, total_capacity - used_5h)

        resets_at_5h = five_hour_info.get("resets_at")
        if resets_at_5h:
            r_sec = parse_timestamp(resets_at_5h)
            if r_sec is not None:
                release_sec = r_sec
                seconds_remaining = max(0, int(release_sec - now_sec))
                release_time = datetime.fromtimestamp(release_sec, tz=timezone.utc).isoformat()
                native_api_fields.append("release")

        # Weekly window from official API
        util_7d = seven_day_info.get("utilization")
        if util_7d is not None:
            weekly_usage_percentage = round(float(util_7d), 1)
            weekly_used_capacity = round(weekly_total_capacity * (weekly_usage_percentage / 100.0))
            weekly_available_capacity = max(0, weekly_total_capacity - weekly_used_capacity)
        else:
            weekly_usage_percentage = min(100.0, round((total_weekly_messages / weekly_total_capacity) * 100.0, 1)) if weekly_total_capacity > 0 else 0.0
            weekly_available_capacity = max(0, weekly_total_capacity - total_weekly_messages)
            weekly_used_capacity = total_weekly_messages

        resets_at_7d = seven_day_info.get("resets_at")
        if resets_at_7d:
            w_sec = parse_timestamp(resets_at_7d)
            if w_sec is not None:
                cycle_reset_sec = w_sec
                weekly_seconds_remaining = max(0, int(cycle_reset_sec - now_sec))
                cycle_reset_time = datetime.fromtimestamp(cycle_reset_sec, tz=timezone.utc).isoformat()
                weekly_api_fields.append("release")
    else:
        # Fallback to local calculation
        weekly_usage_percentage = min(100.0, round((total_weekly_messages / weekly_total_capacity) * 100.0, 1)) if weekly_total_capacity > 0 else 0.0
        weekly_available_capacity = max(0, weekly_total_capacity - total_weekly_messages)
        weekly_used_capacity = total_weekly_messages

    native_window = {
        "type": "5h",
        "source": native_source,
        "api_fields": native_api_fields,
        # The usage API has no duration field: it is deduced from the five_hour/seven_day bucket names
        "window_seconds": CLAUDE_5H_SECONDS,
        "total_capacity": total_capacity,
        "used_capacity": used_5h,
        "available_capacity": available_capacity,
        "usage_percentage": usage_percentage,
        "release_time": release_time,
        "seconds_remaining": seconds_remaining,
        "tokens_used": tokens_5h,
        "messages_used": used_5h,
    }

    weekly_window = {
        "source": weekly_source,
        "api_fields": weekly_api_fields,
        "total_tokens_or_turns": None,
        "total_capacity": weekly_total_capacity,
        "used_capacity": weekly_used_capacity,
        "available_capacity": weekly_available_capacity,
        "usage_percentage": weekly_usage_percentage,
        "tokens_used": total_weekly_tokens,
        "messages_used": total_weekly_messages,
        "cycle_reset_time": cycle_reset_time,
        "seconds_remaining": weekly_seconds_remaining,
        "window_seconds": CLAUDE_7D_SECONDS,
    }

    # Breakdown since the last weekly reset (API reset - 7d, else rolling 7d)
    since_sec = now_sec - CLAUDE_7D_SECONDS
    api_reset = parse_timestamp(((api_data or {}).get("seven_day") or {}).get("resets_at"))
    if api_reset is not None:
        since_sec = min(now_sec, api_reset - CLAUDE_7D_SECONDS)
    by_model, by_project = scan_project_token_breakdown(projects_dir, since_sec)
    usage_details: dict[str, Any] = {}
    if by_model:
        usage_details["tokens_by_model"] = _sorted_breakdown(by_model, "model")
    if by_project:
        usage_details["tokens_by_project"] = _sorted_breakdown(by_project, "project")
    if usage_details:
        usage_details["since"] = datetime.fromtimestamp(since_sec, tz=timezone.utc).isoformat()
    extra_usage = parse_extra_usage(api_data)
    if extra_usage:
        usage_details["extra_usage"] = extra_usage

    result = {
        "health": health,
        "native_window": native_window,
        "weekly_window": weekly_window,
        "free_trial_invites": invites,
    }
    if usage_details:
        result["usage_details"] = usage_details
    return result
