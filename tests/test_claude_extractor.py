"""Automated tests for Claude native extractor."""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.contract import validate_status_contract
from ai_usage_collector.extractors.claude import (
    DEFAULT_CAPACITY_BY_TIER,
    extract_claude_status,
    extract_invites,
    fetch_claude_usage_api,
    parse_timestamp,
    read_daily_activity_and_tokens,
    read_history_timestamps,
    resolve_tier_capacity,
    scan_recent_project_tokens,
)


def test_parse_timestamp():
    # Millisecond timestamp
    assert parse_timestamp(1792501688107) == 1792501688.107

    # Second timestamp
    assert parse_timestamp(1792501688) == 1792501688.0

    # Numeric string
    assert parse_timestamp("1792501688107") == 1792501688.107

    # ISO string with Z
    iso_z = "2026-10-20T13:00:00Z"
    assert parse_timestamp(iso_z) == 1792501200.0

    # ISO string with offset
    iso_offset = "2026-10-20T13:00:00+00:00"
    assert parse_timestamp(iso_offset) == 1792501200.0

    # Invalid values
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not-a-timestamp") is None
    assert parse_timestamp(-50) is None


def test_resolve_tier_capacity():
    # Default pro
    cap_pro = resolve_tier_capacity(
        {}, {"metadata": {"subscription_type": "pro"}}
    )
    assert cap_pro == DEFAULT_CAPACITY_BY_TIER["pro"]

    # Team
    cap_team = resolve_tier_capacity(
        {}, {"metadata": {"subscription_type": "team"}}
    )
    assert cap_team == DEFAULT_CAPACITY_BY_TIER["team"]

    # Free
    cap_free = resolve_tier_capacity(
        {}, {"metadata": {"rate_limit_tier": "free"}}
    )
    assert cap_free == DEFAULT_CAPACITY_BY_TIER["free"]

    # Config override
    cap_custom = resolve_tier_capacity(
        {"rate_limit_capacity": 60}, {"metadata": {"subscription_type": "pro"}}
    )
    assert cap_custom == 60


def test_claude_extractor_fresh_empty_directory(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-test",
            "subscriptionType": "pro",
            "expiresAt": "2026-10-25T12:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "test_claude",
        "provider": "claude",
        "claude_dir": str(claude_dir),
        "credential_path": str(claude_dir / ".credentials.json"),
    }

    result = extract_claude_status(account, now=now)

    assert result["health"]["status"] == "valid"

    nw = result["native_window"]
    assert nw["type"] == "5h"
    assert nw["used_capacity"] == 0
    assert nw["total_capacity"] == 45
    assert nw["available_capacity"] == 45
    assert nw["usage_percentage"] == 0.0
    assert nw["release_time"] is None
    assert nw["seconds_remaining"] is None

    ww = result["weekly_window"]
    assert ww["used_capacity"] == 0
    assert ww["tokens_used"] == 0
    assert ww["cycle_reset_time"] is None
    assert ww["seconds_remaining"] is None

    invites = result["free_trial_invites"]
    assert invites["available_count"] == 0
    assert invites["invite_url"] is None


def test_claude_extractor_active_5h_and_weekly_usage(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-test",
            "subscriptionType": "pro",
            "expiresAt": "2026-10-25T12:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    # Reference point: 2026-10-20 15:00:00 UTC
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ts_ms = int(now.timestamp() * 1000)

    # Interactions:
    # 1. 8 days ago (outside 7d): now - 8 days
    # 2. 2 days ago (inside 7d, outside 5h): now - 48h
    # 3. 4 hours ago (inside 5h, earliest in 5h): now - 4h  -> 11:00 UTC
    # 4. 2 hours ago (inside 5h): now - 2h -> 13:00 UTC
    # 5. 30 min ago (inside 5h): now - 30m -> 14:30 UTC
    ts_8d = now_ts_ms - (8 * 86400 * 1000)
    ts_2d = now_ts_ms - (2 * 86400 * 1000)
    ts_4h = now_ts_ms - (4 * 3600 * 1000)
    ts_2h = now_ts_ms - (2 * 3600 * 1000)
    ts_30m = now_ts_ms - (30 * 60 * 1000)

    history_lines = [
        {"display": "prompt 8d", "timestamp": ts_8d},
        {"display": "prompt 2d", "timestamp": ts_2d},
        {"display": "prompt 4h", "timestamp": ts_4h},
        {"display": "prompt 2h", "timestamp": ts_2h},
        {"display": "prompt 30m", "timestamp": ts_30m},
    ]

    history_file = claude_dir / "history.jsonl"
    with open(history_file, "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    account = {
        "id": "test_claude",
        "provider": "claude",
        "claude_dir": str(claude_dir),
    }

    result = extract_claude_status(account, now=now)

    nw = result["native_window"]
    assert nw["type"] == "5h"
    assert nw["used_capacity"] == 3  # 4h, 2h, 30m
    assert nw["total_capacity"] == 45
    assert nw["available_capacity"] == 42
    assert nw["usage_percentage"] == round((3 / 45) * 100, 1)  # 6.7%

    # Earliest in 5h was 4h ago (11:00 UTC).
    # 5h window from 11:00 UTC resets at 16:00 UTC (1 hour from now = 3600 seconds)
    expected_release = datetime.fromtimestamp(ts_4h / 1000 + 18000, tz=timezone.utc).isoformat()
    assert nw["release_time"] == expected_release
    assert nw["seconds_remaining"] == 3600

    ww = result["weekly_window"]
    # 4 interactions in 7 days (2d, 4h, 2h, 30m)
    assert ww["used_capacity"] == 4
    # Oldest in 7d was ts_2d. Cycle reset is ts_2d + 7 days
    expected_cycle_reset = datetime.fromtimestamp(ts_2d / 1000 + (7 * 86400), tz=timezone.utc).isoformat()
    assert ww["cycle_reset_time"] == expected_cycle_reset
    assert ww["seconds_remaining"] == (5 * 86400)  # 5 days remaining


def test_claude_extractor_quota_exhausted_or_exceeded(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-test",
            "subscriptionType": "pro",
            "expiresAt": "2026-10-25T12:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ts_ms = int(now.timestamp() * 1000)

    # 15 interactions in the last 2 hours
    history_lines = [
        {"display": f"prompt {i}", "timestamp": now_ts_ms - (i * 300 * 1000)}
        for i in range(15)
    ]
    with open(claude_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    # Custom capacity limit of 10
    account = {
        "id": "test_claude",
        "provider": "claude",
        "claude_dir": str(claude_dir),
        "rate_limit_capacity": 10,
    }

    result = extract_claude_status(account, now=now)
    nw = result["native_window"]
    assert nw["total_capacity"] == 10
    assert nw["used_capacity"] == 15
    assert nw["available_capacity"] == 0
    assert nw["usage_percentage"] == 100.0
    assert nw["seconds_remaining"] > 0
    assert nw["release_time"] is not None


def test_claude_extractor_free_trial_invites_fallback(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # Manual invite url in config
    account = {
        "id": "default",
        "provider": "claude",
        "claude_dir": str(claude_dir),
        "manual_invite_url": "https://claude.ai/referral/FRIENDS2026",
    }

    result = extract_claude_status(account)
    invites = result["free_trial_invites"]
    assert invites["available_count"] == 1
    assert invites["invite_url"] == "https://claude.ai/referral/FRIENDS2026"

    # With manual_invite_count
    account_with_count = {
        "id": "default",
        "provider": "claude",
        "claude_dir": str(claude_dir),
        "manual_invite_url": "https://claude.ai/referral/FRIENDS2026",
        "manual_invite_count": 5,
    }
    result2 = extract_claude_status(account_with_count)
    assert result2["free_trial_invites"]["available_count"] == 5

    # Discovered from local settings.json
    (claude_dir / "settings.json").write_text(
        json.dumps({
            "referralUrl": "https://claude.ai/referral/FROM_SETTINGS",
            "invitesAvailable": 2,
        })
    )
    result3 = extract_claude_status({"claude_dir": str(claude_dir)})
    assert result3["free_trial_invites"]["available_count"] == 2
    assert result3["free_trial_invites"]["invite_url"] == "https://claude.ai/referral/FROM_SETTINGS"


def test_claude_extractor_session_expired(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # Expired token (expiresAt in 2020)
    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-expired",
            "subscriptionType": "pro",
            "expiresAt": "2020-01-01T00:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    account = {
        "id": "expired_acc",
        "provider": "claude",
        "claude_dir": str(claude_dir),
    }

    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    result = extract_claude_status(account, now=now)

    assert result["health"]["status"] == "session_expired"
    assert "expirada" in result["health"]["message"].lower()


def test_claude_extractor_corrupted_files_handled_gracefully(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # Broken history file with garbage lines
    history_file = claude_dir / "history.jsonl"
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    history_file.write_text(
        "INVALID JSON LINE\n"
        "\n"
        '{"timestamp": "not-a-number"}\n'
        f'{{"timestamp": {now_ms - 1000}, "display": "valid prompt"}}\n'
        "CORRUPT TEXT }}}"
    )

    # Broken stats-cache.json
    stats_file = claude_dir / "stats-cache.json"
    stats_file.write_text("{ unclosed json: ")

    account = {
        "id": "corrupt_test",
        "provider": "claude",
        "claude_dir": str(claude_dir),
    }

    # Must not crash
    result = extract_claude_status(account)
    nw = result["native_window"]
    assert nw["used_capacity"] == 1  # Successfully parsed the single valid line


def test_claude_extractor_stats_cache_and_project_tokens(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    today_str = "2026-10-20"
    yesterday_str = "2026-10-19"

    # Stats-cache with dailyModelTokens and dailyActivity
    stats_data = {
        "dailyActivity": [
            {"date": yesterday_str, "messageCount": 10, "toolCallCount": 5},
            {"date": today_str, "messageCount": 15, "toolCallCount": 7},
        ],
        "dailyModelTokens": [
            {"date": yesterday_str, "tokensByModel": {"sonnet": 50000, "opus": 20000}},
            {"date": today_str, "tokensByModel": {"sonnet": 80000}},
        ],
    }
    (claude_dir / "stats-cache.json").write_text(json.dumps(stats_data))

    # Project session with tokens
    projects_dir = claude_dir / "projects" / "test-proj"
    projects_dir.mkdir(parents=True)
    session_file = projects_dir / "session1.jsonl"
    session_line = {
        "type": "assistant",
        "timestamp": "2026-10-20T14:00:00Z",
        "message": {
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 300,
            }
        },
    }
    session_file.write_text(json.dumps(session_line) + "\n")

    account = {
        "id": "token_test",
        "provider": "claude",
        "claude_dir": str(claude_dir),
    }

    result = extract_claude_status(account, now=now)
    nw = result["native_window"]
    ww = result["weekly_window"]

    # 1500 tokens in the 5h window from project file
    assert nw["tokens_used"] == 1500
    # 50k + 20k + 80k = 150k from stats + 1500 from project = 151500
    assert ww["tokens_used"] == 151500
    # 10 + 15 = 25 messages from stats
    assert ww["used_capacity"] == 25


def test_collector_integration_with_claude_native_extractor(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-test",
            "subscriptionType": "pro",
            "expiresAt": "2026-10-25T12:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    # Add 2 prompt turns in last hour
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    history_file = claude_dir / "history.jsonl"
    history_file.write_text(
        f'{{"timestamp": {now_ms - 1800000}, "display": "p1"}}\n'
        f'{{"timestamp": {now_ms - 600000}, "display": "p2"}}\n'
    )

    custom_cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "my_claude",
                        "label": "Claude Work",
                        "source": "auto",
                        "claude_dir": str(claude_dir),
                        "credential_path": str(claude_dir / ".credentials.json"),
                        "manual_invite_url": "https://claude.ai/invite/XYZ",
                    }
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    config_path.write_text(json.dumps(custom_cfg))

    status = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)

    assert validate_status_contract(status) is True
    claude_agent = status["agents"]["claude"]
    assert claude_agent["status"] == "ok"
    assert len(claude_agent["accounts"]) == 1

    acc = claude_agent["accounts"][0]
    assert acc["id"] == "my_claude"
    assert acc["label"] == "Claude Work"
    assert acc["health"]["status"] == "valid"

    # Native window check
    nw = acc["native_window"]
    assert nw["type"] == "5h"
    assert nw["used_capacity"] == 2
    assert nw["total_capacity"] == 45
    assert nw["available_capacity"] == 43
    assert nw["usage_percentage"] == round((2 / 45) * 100, 1)
    assert nw["release_time"] is not None
    assert nw["seconds_remaining"] is not None

    # Free trial invites check
    assert acc["free_trial_invites"]["available_count"] == 1
    assert acc["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/XYZ"


def test_claude_extractor_with_real_environment_if_present():
    real_claude_dir = Path("~/.claude").expanduser().resolve()
    if not (real_claude_dir / ".credentials.json").exists():
        pytest.skip("No real ~/.claude/.credentials.json present on machine")

    result = extract_claude_status({"claude_dir": str(real_claude_dir)})
    assert result["health"]["detected"] is True

    nw = result["native_window"]
    assert nw["type"] == "5h"
    assert nw["total_capacity"] is not None
    assert nw["used_capacity"] is not None
    assert nw["available_capacity"] is not None
    assert 0.0 <= nw["usage_percentage"] <= 100.0

    ww = result["weekly_window"]
    assert ww["used_capacity"] is not None


def test_fetch_claude_usage_api_success():
    fake_body = json.dumps({
        "five_hour": {"utilization": 22.5, "resets_at": "2026-10-20T18:00:00Z"},
        "seven_day": {"utilization": 87.0, "resets_at": "2026-10-25T12:00:00Z"},
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = fake_body

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        data = fetch_claude_usage_api("test-token")
        assert data is not None
        assert data["five_hour"]["utilization"] == 22.5
        assert data["seven_day"]["utilization"] == 87.0

        # Verify request headers
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test-token"
        assert req.get_header("Accept") == "application/json"


def test_fetch_claude_usage_api_http_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)):
        data = fetch_claude_usage_api("bad-token")
        assert data is None


def test_fetch_claude_usage_api_timeout():
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        data = fetch_claude_usage_api("test-token")
        assert data is None


def test_extract_claude_status_with_official_api(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-live",
            "subscriptionType": "pro",
            "expiresAt": "2026-10-25T12:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    fake_api_response = {
        "five_hour": {
            "utilization": 20.0,
            "resets_at": "2026-10-20T18:00:00Z",
        },
        "seven_day": {
            "utilization": 85.0,
            "resets_at": "2026-10-25T12:00:00Z",
        },
    }

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "official_claude",
        "provider": "claude",
        "claude_dir": str(claude_dir),
        "weekly_capacity": 315,
    }

    with patch("ai_usage_collector.extractors.claude.fetch_claude_usage_api", return_value=fake_api_response):
        res = extract_claude_status(account, now=now)

    nw = res["native_window"]
    assert nw["usage_percentage"] == 20.0
    assert nw["used_capacity"] == 9  # 20% of 45
    assert nw["total_capacity"] == 45
    assert nw["available_capacity"] == 36
    assert nw["seconds_remaining"] == 3 * 3600  # 15:00 to 18:00 = 3h

    ww = res["weekly_window"]
    assert ww["usage_percentage"] == 85.0
    assert ww["total_capacity"] == 315
    assert ww["available_capacity"] == 47  # 15% of 315
    assert ww["used_capacity"] == 268  # 85% of 315
    assert ww["cycle_reset_time"] == "2026-10-25T12:00:00+00:00"


def test_extract_claude_status_fallback_when_api_fails(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-live",
            "subscriptionType": "pro",
            "expiresAt": "2026-10-25T12:00:00Z",
        }
    }
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))

    # Add 2 messages in last hour
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    history_file = claude_dir / "history.jsonl"
    history_file.write_text(
        f'{{"timestamp": {now_ms - 1800000}, "display": "p1"}}\n'
        f'{{"timestamp": {now_ms - 600000}, "display": "p2"}}\n'
    )

    account = {
        "id": "fallback_claude",
        "provider": "claude",
        "claude_dir": str(claude_dir),
    }

    # API returns None (offline / network failure)
    with patch("ai_usage_collector.extractors.claude.fetch_claude_usage_api", return_value=None):
        res = extract_claude_status(account, now=now)

    nw = res["native_window"]
    assert nw["used_capacity"] == 2
    assert nw["total_capacity"] == 45
    assert nw["available_capacity"] == 43
    assert nw["usage_percentage"] == round((2 / 45) * 100, 1)

    ww = res["weekly_window"]
    assert ww["total_capacity"] == 45 * 7
    assert ww["used_capacity"] == 2
    assert ww["available_capacity"] == (45 * 7) - 2
    assert ww["usage_percentage"] == round((2 / (45 * 7)) * 100, 1)

