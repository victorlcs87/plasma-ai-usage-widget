"""Automated tests for Gemini native extractor."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import subprocess
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.contract import validate_status_contract
from ai_usage_collector.extractors.gemini import (
    DEFAULT_GEMINI_CAPACITY_BY_TIER,
    extract_gemini_invites,
    extract_gemini_status,
    fetch_gemini_quota_api,
    get_gemini_keyring_token,
    parse_gemini_quota_buckets,
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


def test_get_gemini_keyring_token_success():
    fake_json = json.dumps({"token": {"access_token": "ya29.keyring_token"}})
    mock_proc = MagicMock(returncode=0, stdout=fake_json)

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        tok = get_gemini_keyring_token()
        assert tok == "ya29.keyring_token"
        assert mock_run.call_args[0][0] == [
            "secret-tool", "lookup", "service", "gemini", "username", "antigravity"
        ]


def test_get_gemini_keyring_token_failures():
    # Return code failure
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
        assert get_gemini_keyring_token() is None

    # Subprocess exception (e.g. secret-tool not found or timeout)
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert get_gemini_keyring_token() is None


def test_fetch_gemini_quota_api_success():
    fake_body = json.dumps({
        "gemini-5h": {"remainingFraction": 0.8, "resetTime": "2026-10-20T18:00:00Z"},
        "gemini-weekly": {"remainingFraction": 0.35, "resetTime": "2026-10-25T12:00:00Z"},
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = fake_body

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        data = fetch_gemini_quota_api("test-token")
        assert data is not None
        assert "gemini-5h" in data
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test-token"
        assert req.get_header("Content-type") == "application/json"
        assert req.data == b"{}"


def test_parse_gemini_quota_buckets():
    # Format 1: direct dictionary keys
    data1 = {
        "gemini-5h": {"remainingFraction": 0.8},
        "gemini-weekly": {"remainingFraction": 0.5},
    }
    b5h, bw = parse_gemini_quota_buckets(data1)
    assert b5h["remainingFraction"] == 0.8
    assert bw["remainingFraction"] == 0.5

    # Format 2: list of buckets
    data2 = {
        "buckets": [
            {"window": "5h", "remainingFraction": 0.7},
            {"window": "weekly", "remainingFraction": 0.4},
        ]
    }
    b5h2, bw2 = parse_gemini_quota_buckets(data2)
    assert b5h2["remainingFraction"] == 0.7
    assert bw2["remainingFraction"] == 0.4


def test_extract_gemini_status_with_official_api(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    creds = {"access_token": "ya29.fallback"}
    (gemini_dir / "oauth_creds.json").write_text(json.dumps(creds))

    fake_api_response = {
        "gemini-5h": {
            "remainingFraction": 0.75,  # 1.0 - 0.75 = 25.0% used
            "resetTime": "2026-10-20T18:00:00Z",
        },
        "gemini-weekly": {
            "remainingFraction": 0.30,  # 1.0 - 0.30 = 70.0% used
            "resetTime": "2026-10-25T12:00:00Z",
        },
    }

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "official_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
        "weekly_capacity": 700,
    }

    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value="ya29.keyring"), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=fake_api_response):
        res = extract_gemini_status(account, now=now)

    nw = res["native_window"]
    assert nw["usage_percentage"] == 25.0
    assert nw["total_capacity"] == 100
    assert nw["available_capacity"] == 75  # 75% available
    assert nw["used_capacity"] == 25  # 25% used
    assert nw["seconds_remaining"] == 3 * 3600

    ww = res["weekly_window"]
    assert ww["usage_percentage"] == 70.0
    assert ww["total_capacity"] == 700
    assert ww["available_capacity"] == 210  # 30% available of 700
    assert ww["used_capacity"] == 490  # 70% used of 700
    assert ww["cycle_reset_time"] == "2026-10-25T12:00:00+00:00"


def test_extract_gemini_status_fallback_when_api_fails(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    creds = {"access_token": "ya29.fallback"}
    (gemini_dir / "oauth_creds.json").write_text(json.dumps(creds))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    history_file = gemini_dir / "history.jsonl"
    history_file.write_text(
        f'{{"timestamp": {now_ms - 1800000}, "display": "g1"}}\n'
        f'{{"timestamp": {now_ms - 600000}, "display": "g2"}}\n'
    )

    account = {
        "id": "fallback_gemini",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
    }

    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value=None), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=None):
        res = extract_gemini_status(account, now=now)

    nw = res["native_window"]
    assert nw["used_capacity"] == 2
    assert nw["total_capacity"] == 100
    assert nw["available_capacity"] == 98
    assert nw["usage_percentage"] == round((2 / 100) * 100, 1)

    ww = res["weekly_window"]
    assert ww["total_capacity"] == 100 * 7
    assert ww["used_capacity"] == 2
    assert ww["available_capacity"] == (100 * 7) - 2
    assert ww["usage_percentage"] == round((2 / (100 * 7)) * 100, 1)
    # Sem resumo de cota: fallback da heuristica local (janela diaria)
    assert nw["type"] == "daily"
    assert nw["window_seconds"] == 86400
    assert ww["window_seconds"] == 7 * 86400


def test_extract_gemini_status_window_duration_from_quota_summary(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_text(json.dumps({"access_token": "ya29.x"}))
    api = {"buckets": [
        {"bucketId": "gemini-5h", "remainingFraction": 0.5, "resetTime": "2026-10-20T16:00:00Z"},
        {"bucketId": "gemini-weekly", "remainingFraction": 0.5},
    ]}
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {"id": "g", "provider": "gemini", "gemini_dir": str(gemini_dir)}

    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value=None), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=api):
        res = extract_gemini_status(account, now=now)

    assert res["native_window"]["type"] == "5h"
    assert res["native_window"]["window_seconds"] == 18000
    assert res["weekly_window"]["window_seconds"] == 7 * 86400


def test_gemini_5h_bucket_without_reset_does_not_mix_daily_heuristic(tmp_path):
    # M3: bucket 5h sem resetTime -> sem seconds_remaining de ~23h da heuristica diaria
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_text(json.dumps({"access_token": "ya29.x"}))
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    (gemini_dir / "history.jsonl").write_text(f'{{"timestamp": {now_ms - 3600 * 1000}}}\n')
    api = {"buckets": [{"bucketId": "gemini-5h", "remainingFraction": 0.5}]}
    account = {"id": "g", "provider": "gemini", "gemini_dir": str(gemini_dir)}

    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value=None), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=api):
        res = extract_gemini_status(account, now=now)

    nw = res["native_window"]
    assert nw["type"] == "5h"
    assert nw["usage_percentage"] == 50.0
    assert nw["seconds_remaining"] is None
    assert nw["release_time"] is None


def test_extract_gemini_status_expired_file_overridden_by_keyring_and_api(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    cred_file = gemini_dir / "oauth_creds.json"

    # Outdated credentials with past expiry_date
    expired_creds = {
        "access_token": "ya29.expired_old",
        "expiry_date": 1000000000000,  # Sep 2001
        "token_type": "Bearer",
    }
    cred_file.write_text(json.dumps(expired_creds))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "default",
        "provider": "gemini",
        "gemini_dir": str(gemini_dir),
        "credential_path": str(cred_file),
    }

    id_tok = "h." + "eyJlbWFpbCI6ICJhY3RpdmVAZ21haWwuY29tIn0" + ".s"
    fake_keyring_raw = {
        "token": {
            "access_token": "ya29.keyring_active_token",
            "token_type": "Bearer",
            "refresh_token": "1//refresh_active",
            "expiry": "2026-10-20T18:00:00Z",
        },
        "id_token": id_tok,
    }

    fake_api_response = {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {
                        "bucketId": "gemini-5h",
                        "window": "5h",
                        "remainingFraction": 0.85,
                        "resetTime": "2026-10-20T20:00:00Z",
                    },
                    {
                        "bucketId": "gemini-weekly",
                        "window": "weekly",
                        "remainingFraction": 0.90,
                        "resetTime": "2026-10-25T12:00:00Z",
                    },
                ],
            }
        ]
    }

    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value="ya29.keyring_active_token"), \
         patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_raw", return_value=fake_keyring_raw), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=fake_api_response):
        res = extract_gemini_status(account, now=now)

    assert res["health"]["status"] == "valid"
    assert res["health"]["message"] == "Credencial Gemini ativa detectada via API oficial"
    assert res["health"]["metadata"]["email"] == "active@gmail.com"
    assert res["native_window"]["usage_percentage"] == 15.0  # (1.0 - 0.85) * 100
    assert res["native_window"]["available_capacity"] == 85
    assert res["weekly_window"]["usage_percentage"] == 10.0  # (1.0 - 0.90) * 100
    assert res["weekly_window"]["available_capacity"] == 630

    # Verify file was synchronized with 0600 permissions and active token
    assert cred_file.exists()
    assert (cred_file.stat().st_mode & 0o777) == 0o600
    synced = json.loads(cred_file.read_text(encoding="utf-8"))
    assert synced["access_token"] == "ya29.keyring_active_token"
    assert synced["refresh_token"] == "1//refresh_active"


def test_collector_gemini_status_json_reflects_ok_with_expired_file_but_active_keyring(tmp_path):
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    gemini_dir = tmp_path / "gemini"
    gemini_dir.mkdir(parents=True)
    cred_file = gemini_dir / "oauth_creds.json"

    # Expired token in file
    cred_file.write_text(json.dumps({
        "access_token": "ya29.expired",
        "expiry_date": 1000000000000,
    }))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    config_path = config_dir / "config.json"
    config_content = {
        "version": 1,
        "agents": {
            "claude": {"accounts": []},
            "codex": {"accounts": []},
            "gemini": {
                "accounts": [
                    {
                        "id": "default",
                        "label": "Gemini (Padrão)",
                        "source": "auto",
                        "credential_path": str(cred_file),
                        "gemini_dir": str(gemini_dir),
                    }
                ]
            },
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_content))

    cache_path = cache_dir / "status.json"

    id_tok = "h." + "eyJlbWFpbCI6ICJ1c2VyLmtleXJpbmdAZ21haWwuY29tIn0" + ".s"
    fake_keyring_raw = {
        "token": {
            "access_token": "ya29.keyring_token",
            "token_type": "Bearer",
            "refresh_token": "1//refresh_val",
            "expiry": "2026-10-20T18:00:00Z",
        },
        "id_token": id_tok,
    }

    fake_api_response = {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {
                        "bucketId": "gemini-5h",
                        "window": "5h",
                        "remainingFraction": 1.0,
                    },
                    {
                        "bucketId": "gemini-weekly",
                        "window": "weekly",
                        "remainingFraction": 0.95,
                    },
                ],
            }
        ]
    }

    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value="ya29.keyring_token"), \
         patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_raw", return_value=fake_keyring_raw), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=fake_api_response), \
         patch("ai_usage_collector.discovery.get_gemini_keyring_credentials", return_value={
             "access_token": "ya29.keyring_token",
             "refresh_token": "1//refresh_val",
             "id_token": id_tok,
             "expiry": "2026-10-20T18:00:00Z",
             "token_type": "Bearer",
         }):
        status = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)

    assert validate_status_contract(status)
    gemini_agent = status["agents"]["gemini"]
    assert gemini_agent["status"] == "ok"
    assert len(gemini_agent["accounts"]) == 1

    acc = gemini_agent["accounts"][0]
    assert acc["health"]["status"] == "valid"
    assert "user.keyring@gmail.com" in acc["label"]
    assert acc["native_window"]["usage_percentage"] == 0.0
    assert acc["native_window"]["available_capacity"] == 100

    # Verify status.json persisted on disk
    assert cache_path.exists()
    disk_data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert disk_data["agents"]["gemini"]["status"] == "ok"
    assert disk_data["agents"]["gemini"]["accounts"][0]["health"]["status"] == "valid"


def _gemini_sources(tmp_path, api_response):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir(exist_ok=True)
    (gemini_dir / "oauth_creds.json").write_text(json.dumps({"access_token": "ya29.fallback"}))
    account = {"id": "g", "provider": "gemini", "gemini_dir": str(gemini_dir)}
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    with patch("ai_usage_collector.extractors.gemini.get_gemini_keyring_token", return_value="ya29.keyring"), \
         patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=api_response):
        res = extract_gemini_status(account, now=now)
    return res["native_window"], res["weekly_window"]


def test_gemini_source_markers_only_claim_what_was_read(tmp_path):
    full = {"gemini-5h": {"bucketId": "gemini-5h", "remainingFraction": 0.5, "resetTime": "2026-10-20T18:00:00Z"},
            "gemini-weekly": {"bucketId": "gemini-weekly", "remainingFraction": 0.5, "resetTime": "2026-10-25T12:00:00Z"}}
    nw, ww = _gemini_sources(tmp_path, full)
    assert (nw["source"], nw["api_fields"], ww["source"]) == ("api", ["duration", "release"], "api")

    # Sem resetTime nem duracao no bucket: duracao e release sao assumidos, nao lidos
    nw, _ = _gemini_sources(tmp_path, {"gemini-5h": {"remainingFraction": 0.5}})
    assert nw["source"] == "api" and nw["api_fields"] == []

    # Resposta sem bucket reconhecivel ou sem remainingFraction: nada e "removido"
    for junk in ({"unrelated": 1}, {"gemini-5h": {}}, {"gemini-5h": {"resetTime": "2026-10-20T18:00:00Z"}}):
        nw, ww = _gemini_sources(tmp_path, junk)
        assert (nw["source"], ww["source"]) == ("local", "local")

    nw, ww = _gemini_sources(tmp_path, {"gemini-5h": full["gemini-5h"]})
    assert (nw["source"], ww["source"]) == ("api", "api_missing")
