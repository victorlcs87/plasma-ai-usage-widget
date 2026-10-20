"""Automated tests for Gemini native extractor."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.contract import validate_status_contract
from ai_usage_collector.extractors.gemini import (
    DEFAULT_GEMINI_CAPACITY_BY_TIER,
    extract_gemini_invites,
    extract_gemini_status,
    parse_timestamp,
    read_gemini_history_timestamps,
    read_gemini_sqlite_summaries,
    resolve_gemini_capacity,
)


def test_parse_timestamp():
    # Milliseconds
    assert parse_timestamp(1792501688107) == 1792501688.107

    # Seconds
    assert parse_timestamp(1792501688) == 1792501688.0

    # Numeric string
    assert parse_timestamp("1792501688") == 1792501688.0

    # ISO string with Z
    iso_z = "2026-10-20T13:00:00Z"
    assert parse_timestamp(iso_z) == 1792501200.0

    # ISO string with offset
    iso_offset = "2026-10-20T13:00:00+00:00"
    assert parse_timestamp(iso_offset) == 1792501200.0

    # SQLite datetime with timezone
    sqlite_tz = "2026-10-20 13:00:00.000000+00:00"
    assert parse_timestamp(sqlite_tz) == 1792501200.0

    # Datetime starting with 0001 (year zero / uninitialized)
    assert parse_timestamp("0001-01-01 00:00:00+00:00") is None

    # Invalid values
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not-a-timestamp") is None
    assert parse_timestamp(-10) is None


def test_resolve_gemini_capacity():
    # Default fallback
    assert resolve_gemini_capacity({}, {}) == 100

    # Pro tier
    assert (
        resolve_gemini_capacity({}, {"metadata": {"subscription_type": "pro"}})
        == DEFAULT_GEMINI_CAPACITY_BY_TIER["pro"]
    )

    # Ultra tier
    assert (
        resolve_gemini_capacity({}, {"metadata": {"subscription_type": "ultra"}})
        == DEFAULT_GEMINI_CAPACITY_BY_TIER["ultra"]
    )

    # Config override
    assert resolve_gemini_capacity({"rate_limit_capacity": 250}, {}) == 250


def test_gemini_extractor_fresh_empty_directory(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    creds = {
        "access_token": "ya29.test",
        "refresh_token": "1//test",
        "token_type": "Bearer",
    }
    (gemini_dir / "oauth_creds.json").write_text(json.dumps(creds))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "test_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
        "credential_path": str(gemini_dir / "oauth_creds.json"),
    }

    result = extract_gemini_status(account, now=now)

    assert result["health"]["status"] == "valid"

    nw = result["native_window"]
    assert nw["type"] == "daily"
    assert nw["used_capacity"] == 0
    assert nw["total_capacity"] == 100
    assert nw["available_capacity"] == 100
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


def test_gemini_extractor_active_daily_and_weekly_usage(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    creds = {
        "access_token": "ya29.test",
        "refresh_token": "1//test",
    }
    (gemini_dir / "oauth_creds.json").write_text(json.dumps(creds))

    # Reference point: 2026-10-20 15:00:00 UTC
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())

    # Interactions:
    # 1. 10 days ago (outside 7d)
    # 2. 3 days ago (inside 7d, outside 24h): now - 72h
    # 3. 18 hours ago (inside 24h, earliest in 24h): now - 18h (64800s)
    # 4. 5 hours ago (inside 24h): now - 5h (18000s)
    # 5. 1 hour ago (inside 24h): now - 1h (3600s)
    dt_10d = (now - timedelta(days=10)).isoformat()
    dt_3d = (now - timedelta(days=3)).isoformat()
    dt_18h = (now - timedelta(hours=18)).isoformat()
    dt_5h = (now - timedelta(hours=5)).isoformat()
    dt_1h = (now - timedelta(hours=1)).isoformat()

    db_path = gemini_dir / "conversation_summaries.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            step_count INTEGER NOT NULL DEFAULT 0,
            last_modified_time DATETIME NOT NULL,
            last_user_input_time DATETIME NOT NULL
        )"""
    )
    cur.executemany(
        "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?)",
        [
            ("c1", 10, dt_10d, dt_10d),
            ("c2", 25, dt_3d, dt_3d),
            ("c3", 15, dt_18h, dt_18h),
            ("c4", 5, dt_5h, dt_5h),
            ("c5", 8, dt_1h, "0001-01-01 00:00:00+00:00"),  # fallback to last_modified_time
        ],
    )
    conn.commit()
    conn.close()

    account = {
        "id": "test_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
    }

    result = extract_gemini_status(account, now=now)

    nw = result["native_window"]
    assert nw["type"] == "daily"
    assert nw["used_capacity"] == 3  # 18h, 5h, 1h
    assert nw["total_capacity"] == 100
    assert nw["available_capacity"] == 97
    assert nw["usage_percentage"] == round((3 / 100) * 100, 1)  # 3.0%

    # Oldest in 24h is 18h ago (dt_18h). 24h from then resets in 6h (21600s).
    expected_release = (now - timedelta(hours=18) + timedelta(days=1)).isoformat()
    assert nw["release_time"] == expected_release
    assert nw["seconds_remaining"] == 21600

    ww = result["weekly_window"]
    # 4 conversations in 7 days (3d, 18h, 5h, 1h)
    assert ww["used_capacity"] == 4
    # Total steps across all conversations
    assert ww["total_tokens_or_turns"] == 10 + 25 + 15 + 5 + 8
    expected_cycle_reset = (now - timedelta(days=3) + timedelta(days=7)).isoformat()
    assert ww["cycle_reset_time"] == expected_cycle_reset
    assert ww["seconds_remaining"] == (4 * 86400)


def test_gemini_extractor_history_jsonl_fallback(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    history_lines = [
        {"display": "prompt 1", "timestamp": now_ms - (3600 * 1000)},
        {"display": "prompt 2", "timestamp": now_ms - (1800 * 1000)},
    ]
    with open(gemini_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    account = {
        "id": "test_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
    }

    result = extract_gemini_status(account, now=now)
    nw = result["native_window"]
    assert nw["used_capacity"] == 2
    assert nw["available_capacity"] == 98


def test_gemini_extractor_quota_exhausted_or_exceeded(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    # 120 prompts in last 12 hours
    history_lines = [
        {"timestamp": now_ms - (i * 300 * 1000), "display": f"query {i}"}
        for i in range(120)
    ]
    with open(gemini_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    account = {
        "id": "test_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
        "rate_limit_capacity": 100,
    }

    result = extract_gemini_status(account, now=now)
    nw = result["native_window"]
    assert nw["total_capacity"] == 100
    assert nw["used_capacity"] == 120
    assert nw["available_capacity"] == 0
    assert nw["usage_percentage"] == 100.0
    assert nw["release_time"] is not None
    assert nw["seconds_remaining"] > 0


def test_gemini_extractor_free_trial_invites_and_fallback(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    # In settings.json
    (gemini_dir / "settings.json").write_text(
        json.dumps({
            "inviteUrl": "https://gemini.google/invite/GEMINI2026",
            "invitesAvailable": 2,
        })
    )

    account = {
        "id": "default",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
    }

    result = extract_gemini_status(account)
    invites = result["free_trial_invites"]
    assert invites["available_count"] == 2
    assert invites["invite_url"] == "https://gemini.google/invite/GEMINI2026"

    # Fallback override in account config
    account_with_override = {
        "id": "default",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
        "manual_invite_url": "https://gemini.google/invite/MANUAL",
        "manual_invite_count": 4,
    }
    result_override = extract_gemini_status(account_with_override)
    assert result_override["free_trial_invites"]["available_count"] == 4


def test_gemini_extractor_corrupted_sqlite_handled_gracefully(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    (gemini_dir / "conversation_summaries.db").write_bytes(b"CORRUPT DB BYTES")

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "test_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
    }

    result = extract_gemini_status(account, now=now)
    assert result["native_window"]["used_capacity"] == 0
    assert result["native_window"]["type"] == "daily"


def test_collector_integration_with_gemini_native_extractor(tmp_path):
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    gemini_dir = tmp_path / "gemini"
    gemini_dir.mkdir(parents=True)

    creds = {
        "access_token": "ya29.test",
        "id_token": "header." + "eyJlbWFpbCI6ICJ1c2VyQGdtYWlsLmNvbSJ9" + ".sig",
    }
    (gemini_dir / "oauth_creds.json").write_text(json.dumps(creds))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    history_lines = [{"timestamp": now_ms - (3600 * 1000), "display": "test prompt"}]
    with open(gemini_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    config_path = config_dir / "config.json"
    config_content = {
        "version": 1,
        "agents": {
            "claude": {"accounts": []},
            "codex": {"accounts": []},
            "gemini": {
                "accounts": [
                    {
                        "id": "personal",
                        "label": "Gemini (Padrão)",
                        "source": "auto",
                        "credential_path": str(gemini_dir / "oauth_creds.json"),
                        "gemini_dir": str(gemini_dir),
                        "manual_invite_url": "https://gemini.google/invite/SHARED",
                    }
                ]
            },
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_content))

    cache_path = cache_dir / "status.json"

    status = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)

    assert validate_status_contract(status)
    gemini_agent = status["agents"]["gemini"]
    assert gemini_agent["status"] == "ok"
    assert len(gemini_agent["accounts"]) == 1

    acc = gemini_agent["accounts"][0]
    assert acc["label"] == "Gemini (user@gmail.com)"
    assert acc["native_window"]["type"] == "daily"
    assert acc["native_window"]["used_capacity"] == 1
    assert acc["free_trial_invites"]["invite_url"] == "https://gemini.google/invite/SHARED"
