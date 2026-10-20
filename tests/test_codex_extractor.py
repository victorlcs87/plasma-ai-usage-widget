"""Automated tests for Codex native extractor."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.contract import validate_status_contract
from ai_usage_collector.extractors.codex import (
    DEFAULT_CODEX_CAPACITY_BY_TIER,
    extract_codex_invites,
    extract_codex_status,
    fetch_codex_usage_api,
    parse_timestamp,
    read_codex_history_timestamps,
    read_codex_logs_timestamps,
    read_codex_sqlite_timestamps,
    resolve_codex_capacity,
)


def test_parse_timestamp():
    # Millisecond timestamp
    assert parse_timestamp(1792501688107) == 1792501688.107

    # Second timestamp
    assert parse_timestamp(1792501688) == 1792501688.0

    # Numeric string
    assert parse_timestamp("1792501688") == 1792501688.0

    # ISO string with Z
    iso_z = "2026-10-20T13:00:00Z"
    assert parse_timestamp(iso_z) == 1792501200.0

    # ISO string with offset
    iso_offset = "2026-10-20T13:00:00+00:00"
    assert parse_timestamp(iso_offset) == 1792501200.0

    # SQLite datetime string without timezone
    sqlite_dt = "2026-10-20 13:00:00"
    assert parse_timestamp(sqlite_dt) == 1792501200.0

    # Invalid values
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not-a-timestamp") is None
    assert parse_timestamp(-50) is None


def test_resolve_codex_capacity():
    # Default fallback
    assert resolve_codex_capacity({}, {}) == 50

    # Auth mode chatgpt
    cap_chatgpt = resolve_codex_capacity({}, {"metadata": {"auth_mode": "chatgpt"}})
    assert cap_chatgpt == DEFAULT_CODEX_CAPACITY_BY_TIER["chatgpt"]

    # Team tier
    cap_team = resolve_codex_capacity({}, {"metadata": {"subscription_type": "team"}})
    assert cap_team == DEFAULT_CODEX_CAPACITY_BY_TIER["team"]

    # Config override
    cap_custom = resolve_codex_capacity({"rate_limit_capacity": 30}, {})
    assert cap_custom == 30


def test_codex_extractor_fresh_empty_directory(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    auth = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "valid_token",
            "account_id": "acc-123",
        },
    }
    (codex_dir / "auth.json").write_text(json.dumps(auth))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "test_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
        "credential_path": str(codex_dir / "auth.json"),
    }

    result = extract_codex_status(account, now=now)

    assert result["health"]["status"] == "valid"

    nw = result["native_window"]
    assert nw["type"] == "3h"
    assert nw["used_capacity"] == 0
    assert nw["total_capacity"] == 50
    assert nw["available_capacity"] == 50
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


def test_codex_extractor_active_3h_and_weekly_usage(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    auth = {
        "auth_mode": "chatgpt",
        "tokens": {"access_token": "token-xyz"},
    }
    (codex_dir / "auth.json").write_text(json.dumps(auth))

    # Reference point: 2026-10-20 15:00:00 UTC
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())

    # Turn timestamps:
    # 1. 10 days ago (outside 7d): now - 10d
    # 2. 2 days ago (inside 7d, outside 3h): now - 48h
    # 3. 2.5 hours ago (inside 3h, earliest in 3h): now - 2.5h (150 min = 9000s)
    # 4. 1 hour ago (inside 3h): now - 1h (3600s)
    # 5. 15 minutes ago (inside 3h): now - 15m (900s)
    ts_10d = now_sec - (10 * 86400)
    ts_2d = now_sec - (2 * 86400)
    ts_2h30 = now_sec - 9000
    ts_1h = now_sec - 3600
    ts_15m = now_sec - 900

    db_path = codex_dir / "thread_history_1.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE thread_turns (
            thread_id TEXT,
            turn_id TEXT,
            started_at INTEGER,
            completed_at INTEGER,
            status TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE thread_items (
            thread_id TEXT,
            turn_id TEXT,
            item_id TEXT,
            created_at_ms INTEGER,
            item_type TEXT
        )"""
    )
    # Insert turns
    cur.executemany(
        "INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?)",
        [
            ("t1", "turn-1", ts_10d, ts_10d + 10, "completed"),
            ("t2", "turn-2", ts_2d, ts_2d + 10, "completed"),
            ("t3", "turn-3", ts_2h30, ts_2h30 + 10, "completed"),
            ("t4", "turn-4", ts_1h, ts_1h + 10, "completed"),
            ("t5", "turn-5", ts_15m, ts_15m + 10, "completed"),
        ],
    )
    conn.commit()
    conn.close()

    account = {
        "id": "test_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
    }

    result = extract_codex_status(account, now=now)

    nw = result["native_window"]
    assert nw["type"] == "3h"
    assert nw["used_capacity"] == 3  # 2h30m, 1h, 15m
    assert nw["total_capacity"] == 50
    assert nw["available_capacity"] == 47
    assert nw["usage_percentage"] == round((3 / 50) * 100, 1)  # 6.0%

    # Oldest in 3h is ts_2h30 (9000s ago). 3h is 10800s.
    # Release time: ts_2h30 + 10800 = now_sec + 1800s (30 minutes from now)
    expected_release = datetime.fromtimestamp(ts_2h30 + 10800, tz=timezone.utc).isoformat()
    assert nw["release_time"] == expected_release
    assert nw["seconds_remaining"] == 1800

    ww = result["weekly_window"]
    # 4 interactions in 7 days (2d, 2h30, 1h, 15m)
    assert ww["used_capacity"] == 4
    expected_cycle_reset = datetime.fromtimestamp(ts_2d + (7 * 86400), tz=timezone.utc).isoformat()
    assert ww["cycle_reset_time"] == expected_cycle_reset
    assert ww["seconds_remaining"] == (5 * 86400)


def test_codex_extractor_history_jsonl_fallback(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())

    history_lines = [
        {"session_id": "s1", "ts": now_sec - 1200, "text": "codex prompt 1"},
        {"session_id": "s2", "ts": now_sec - 600, "text": "codex prompt 2"},
    ]
    with open(codex_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    account = {
        "id": "test_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
    }

    result = extract_codex_status(account, now=now)
    nw = result["native_window"]
    assert nw["used_capacity"] == 2
    assert nw["available_capacity"] == 48


def test_codex_extractor_logs_sqlite_fallback(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())

    logs_db = codex_dir / "logs_2.sqlite"
    conn = sqlite3.connect(logs_db)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE logs (
            id INTEGER PRIMARY KEY,
            ts INTEGER NOT NULL,
            target TEXT NOT NULL,
            feedback_log_body TEXT
        )"""
    )
    cur.execute(
        "INSERT INTO logs (ts, target, feedback_log_body) VALUES (?, ?, ?)",
        (now_sec - 1000, "codex_core::session", "thread submission"),
    )
    conn.commit()
    conn.close()

    account = {
        "id": "test_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
    }

    result = extract_codex_status(account, now=now)
    nw = result["native_window"]
    assert nw["used_capacity"] == 1


def test_codex_extractor_quota_exhausted_or_exceeded(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())

    # 55 prompts in the last hour
    history_lines = [
        {"ts": now_sec - (i * 50), "text": f"prompt {i}"}
        for i in range(55)
    ]
    with open(codex_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    account = {
        "id": "test_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
        "rate_limit_capacity": 50,
    }

    result = extract_codex_status(account, now=now)
    nw = result["native_window"]
    assert nw["total_capacity"] == 50
    assert nw["used_capacity"] == 55
    assert nw["available_capacity"] == 0
    assert nw["usage_percentage"] == 100.0
    assert nw["release_time"] is not None
    assert nw["seconds_remaining"] > 0


def test_codex_extractor_free_trial_invites_and_fallback(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    # In settings.json
    (codex_dir / "settings.json").write_text(
        json.dumps({
            "inviteUrl": "https://chatgpt.com/invite/CODEX123",
            "invitesAvailable": 3,
        })
    )

    account = {
        "id": "default",
        "provider": "codex",
        "codex_dir": str(codex_dir),
    }

    result = extract_codex_status(account)
    invites = result["free_trial_invites"]
    assert invites["available_count"] == 3
    assert invites["invite_url"] == "https://chatgpt.com/invite/CODEX123"

    # Fallback override in account config
    account_with_override = {
        "id": "default",
        "provider": "codex",
        "codex_dir": str(codex_dir),
        "manual_invite_url": "https://chatgpt.com/invite/MANUAL",
        "manual_invite_count": 5,
    }
    result_override = extract_codex_status(account_with_override)
    assert result_override["free_trial_invites"]["available_count"] == 5
    assert result_override["free_trial_invites"]["invite_url"] == "https://chatgpt.com/invite/CODEX123"


def test_codex_extractor_corrupted_sqlite_handled_gracefully(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    # Corrupt sqlite file with garbage bytes
    (codex_dir / "thread_history_1.sqlite").write_bytes(b"CORRUPT SQLITE HEADER AND JUNK")

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "test_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
    }

    result = extract_codex_status(account, now=now)
    assert result["native_window"]["used_capacity"] == 0
    assert result["native_window"]["type"] == "3h"


def test_collector_integration_with_codex_native_extractor(tmp_path):
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    codex_dir = tmp_path / "codex"
    codex_dir.mkdir(parents=True)

    auth = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "valid_token",
            "id_token": "header." + "eyJlbWFpbCI6ICJ1c2VyQG9wZW5haS5jb20ifQ==" + ".sig",
        },
    }
    (codex_dir / "auth.json").write_text(json.dumps(auth))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())

    history_lines = [{"ts": now_sec - 1800, "text": "prompt"}]
    with open(codex_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for entry in history_lines:
            f.write(json.dumps(entry) + "\n")

    config_path = config_dir / "config.json"
    config_content = {
        "version": 1,
        "agents": {
            "claude": {"accounts": []},
            "codex": {
                "accounts": [
                    {
                        "id": "work",
                        "label": "Codex (Padrão)",
                        "source": "auto",
                        "credential_path": str(codex_dir / "auth.json"),
                        "codex_dir": str(codex_dir),
                        "manual_invite_url": "https://chatgpt.com/invite/TEST",
                    }
                ]
            },
            "gemini": {"accounts": []},
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_content))

    cache_path = cache_dir / "status.json"

    status = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)

    assert validate_status_contract(status)
    codex_agent = status["agents"]["codex"]
    assert codex_agent["status"] == "ok"
    assert len(codex_agent["accounts"]) == 1

    acc = codex_agent["accounts"][0]
    assert acc["label"] == "Codex (user@openai.com)"
    assert acc["native_window"]["type"] == "3h"
    assert acc["native_window"]["used_capacity"] == 1
    assert acc["free_trial_invites"]["invite_url"] == "https://chatgpt.com/invite/TEST"


def test_fetch_codex_usage_api_success():
    fake_body = json.dumps({
        "rate_limit": {
            "primary_window": {"used_percent": 30.0, "reset_at": "2026-10-20T18:00:00Z"},
            "secondary_window": {"used_percent": 65.0, "reset_at": "2026-10-25T12:00:00Z"},
        },
        "plan_type": "plus",
        "promo": {
            "invite_url": "https://chatgpt.com/invite/wham-test",
            "available_count": 4,
        },
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = fake_body

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        data = fetch_codex_usage_api("test-token", account_id="acc-12345")
        assert data is not None
        assert data["plan_type"] == "plus"
        assert data["rate_limit"]["primary_window"]["used_percent"] == 30.0

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test-token"
        assert req.get_header("Chatgpt-account-id") == "acc-12345"


def test_fetch_codex_usage_api_errors():
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)):
        assert fetch_codex_usage_api("bad-token") is None

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Timed out")):
        assert fetch_codex_usage_api("tok") is None


def test_extract_codex_status_with_official_api(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    auth_data = {
        "tokens": {
            "access_token": "valid_token",
            "account_id": "acc-999",
        }
    }
    (codex_dir / "auth.json").write_text(json.dumps(auth_data))

    fake_api_response = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 40.0,
                "reset_at": "2026-10-20T18:00:00Z",
            },
            "secondary_window": {
                "used_percent": 75.0,
                "reset_at": "2026-10-25T12:00:00Z",
            },
        },
        "promo": {
            "invite_url": "https://chatgpt.com/invite/official",
            "available_count": 5,
        },
    }

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {
        "id": "official_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
        "weekly_capacity": 350,
    }

    with patch("ai_usage_collector.extractors.codex.fetch_codex_usage_api", return_value=fake_api_response):
        res = extract_codex_status(account, now=now)

    nw = res["native_window"]
    assert nw["usage_percentage"] == 40.0
    assert nw["total_capacity"] == 50
    assert nw["used_capacity"] == 20  # 40% of 50
    assert nw["available_capacity"] == 30
    assert nw["seconds_remaining"] == 3 * 3600

    ww = res["weekly_window"]
    assert ww["usage_percentage"] == 75.0
    assert ww["total_capacity"] == 350
    assert ww["available_capacity"] == 88  # 25% of 350
    assert ww["used_capacity"] == 262  # 75% of 350
    assert ww["cycle_reset_time"] == "2026-10-25T12:00:00+00:00"

    # Promo check
    assert res["free_trial_invites"]["invite_url"] == "https://chatgpt.com/invite/official"
    assert res["free_trial_invites"]["available_count"] == 5


def test_extract_codex_status_fallback_when_api_fails(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    auth_data = {
        "tokens": {
            "access_token": "valid_token",
            "account_id": "acc-999",
        }
    }
    (codex_dir / "auth.json").write_text(json.dumps(auth_data))

    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    history_file = codex_dir / "history.jsonl"
    history_file.write_text(
        f'{{"timestamp": {now_ms - 1800000}, "display": "c1"}}\n'
        f'{{"timestamp": {now_ms - 600000}, "display": "c2"}}\n'
    )

    account = {
        "id": "fallback_codex",
        "provider": "codex",
        "codex_dir": str(codex_dir),
    }

    with patch("ai_usage_collector.extractors.codex.fetch_codex_usage_api", return_value=None):
        res = extract_codex_status(account, now=now)

    nw = res["native_window"]
    assert nw["used_capacity"] == 2
    assert nw["total_capacity"] == 50
    assert nw["available_capacity"] == 48
    assert nw["usage_percentage"] == round((2 / 50) * 100, 1)

    ww = res["weekly_window"]
    assert ww["total_capacity"] == 50 * 7
    assert ww["used_capacity"] == 2
    assert ww["available_capacity"] == (50 * 7) - 2
    assert ww["usage_percentage"] == round((2 / (50 * 7)) * 100, 1)

    # Sem API: a constante vira fallback da heuristica local
    assert nw["type"] == "3h"
    assert nw["window_seconds"] == 3 * 3600
    assert ww["window_seconds"] == 7 * 86400


def test_extract_codex_status_uses_provider_window_duration(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "tok"}}))
    fake_api_response = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 10.0,
                "limit_window_seconds": 18000,
                "reset_at": "2026-10-20T16:00:00Z",
            },
            "secondary_window": {
                "used_percent": 20.0,
                "limit_window_seconds": 604800,
                "reset_at": "2026-10-25T12:00:00Z",
            },
        },
    }
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {"id": "c", "provider": "codex", "codex_dir": str(codex_dir)}

    with patch("ai_usage_collector.extractors.codex.fetch_codex_usage_api", return_value=fake_api_response):
        res = extract_codex_status(account, now=now)

    nw = res["native_window"]
    assert nw["type"] == "5h"
    assert nw["window_seconds"] == 18000
    assert nw["seconds_remaining"] == 3600
    assert res["weekly_window"]["window_seconds"] == 604800


def test_extract_codex_status_window_minutes_and_missing_duration(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "tok"}}))
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    account = {"id": "c", "provider": "codex", "codex_dir": str(codex_dir)}
    api = {"rate_limit": {"primary_window": {"used_percent": 1.0, "window_minutes": 300}}}

    with patch("ai_usage_collector.extractors.codex.fetch_codex_usage_api", return_value=api):
        res = extract_codex_status(account, now=now)
    assert res["native_window"]["window_seconds"] == 18000
    assert res["native_window"]["type"] == "5h"
    # secundaria sem duracao informada: fallback semanal
    assert res["weekly_window"]["window_seconds"] == 7 * 86400


def _codex_api_run(tmp_path, api, history_offsets_sec=()):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "tok"}}))
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    (codex_dir / "history.jsonl").write_text(
        "".join(f'{{"timestamp": {now_ms - off * 1000}}}\n' for off in history_offsets_sec)
    )
    account = {"id": "c", "provider": "codex", "codex_dir": str(codex_dir)}
    with patch("ai_usage_collector.extractors.codex.fetch_codex_usage_api", return_value=api):
        return extract_codex_status(account, now=now), now


def test_codex_infinite_window_duration_does_not_crash(tmp_path):
    # M1: json.loads aceita Infinity; a coleta nao pode cair
    api = json.loads(
        '{"rate_limit": {"primary_window": {"used_percent": 10, "limit_window_seconds": Infinity,'
        ' "reset_after_seconds": Infinity},'
        ' "secondary_window": {"used_percent": 5, "window_minutes": 1e400}}}'
    )
    res, _ = _codex_api_run(tmp_path, api)
    assert res["native_window"]["window_seconds"] == 3 * 3600
    assert res["native_window"]["type"] == "3h"
    assert res["weekly_window"]["window_seconds"] == 7 * 86400


def test_codex_api_duration_without_reset_does_not_mix_heuristic(tmp_path):
    # M2: duracao 5h da API sem reset -> nada de seconds_remaining da heuristica de 3h
    api = {"rate_limit": {"primary_window": {"used_percent": 10.0, "limit_window_seconds": 18000}}}
    res, _ = _codex_api_run(tmp_path, api, history_offsets_sec=(2 * 3600,))
    nw = res["native_window"]
    assert nw["type"] == "5h"
    assert nw["usage_percentage"] == 10.0
    assert nw["seconds_remaining"] is None
    assert nw["release_time"] is None


def test_codex_api_duration_without_percent_recounts_with_api_duration(tmp_path):
    # M2: sem used_percent, a heuristica local usa a duracao informada (5h), nao 3h
    api = {"rate_limit": {"primary_window": {"limit_window_seconds": 18000}}}
    res, _ = _codex_api_run(tmp_path, api, history_offsets_sec=(4 * 3600, 3600))
    nw = res["native_window"]
    assert nw["used_capacity"] == 2
    assert nw["usage_percentage"] == round(2 / 50 * 100, 1)
    assert nw["seconds_remaining"] is None


def test_codex_reset_after_seconds_is_reset_source(tmp_path):
    api = {"rate_limit": {
        "primary_window": {"used_percent": 10.0, "limit_window_seconds": 18000, "reset_after_seconds": 3600},
        "secondary_window": {"used_percent": 5.0, "limit_window_seconds": 604800, "reset_after_seconds": 86400},
    }}
    res, now = _codex_api_run(tmp_path, api)
    assert res["native_window"]["seconds_remaining"] == 3600
    assert res["native_window"]["release_time"] == (now + timedelta(hours=1)).isoformat()
    assert res["weekly_window"]["seconds_remaining"] == 86400


def test_codex_single_weekly_primary_window_becomes_weekly(tmp_path):
    # B1: uma unica janela de 7d na primaria alimenta o medidor semanal
    api = {"rate_limit": {"primary_window": {
        "used_percent": 40.0, "limit_window_seconds": 604800, "reset_at": "2026-10-25T12:00:00Z",
    }}}
    res, _ = _codex_api_run(tmp_path, api)
    ww = res["weekly_window"]
    assert ww["window_seconds"] == 604800
    assert ww["usage_percentage"] == 40.0
    assert ww["cycle_reset_time"] == "2026-10-25T12:00:00+00:00"
    assert res["native_window"]["type"] == "3h"  # sem janela curta informada: fallback
