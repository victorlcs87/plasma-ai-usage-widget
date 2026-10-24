"""Coleta pública após novo login no Claude CLI."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.config import save_config
from tests.test_refresh import FakeHttp, http_error


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("system_expiry,profile_expiry,expected", [
    (2_000_000_000_000, 1_000_000_000_000, "new"),
    (1_000_000_000_000, 2_000_000_000_000, "old"),
])
def test_collect_syncs_unique_claude_identity_without_regression(tmp_path, monkeypatch, system_expiry, profile_expiry, expected):
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: FakeHttp(claude=[{
        "five_hour": {"utilization": 0}, "seven_day": {"utilization": 78},
    }])(req, timeout))
    system = tmp_path / "system"
    profile = tmp_path / "profiles" / "claude" / "one"
    for directory in (system, profile):
        directory.mkdir(parents=True)
        (directory / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "same"}}))
    sys_file = system / ".credentials.json"
    profile_file = profile / ".credentials.json"
    sys_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": "new", "refreshToken": "new-r", "expiresAt": system_expiry}}))
    profile_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": "old", "refreshToken": "old-r", "expiresAt": profile_expiry}}))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(sys_file))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": [{"id": "one", "credential_path": str(profile_file)}]}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config)
    status = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["claude"])
    account = status["agents"]["claude"]["accounts"][0]
    assert json.loads(profile_file.read_text())["claudeAiOauth"]["accessToken"] == expected
    assert account["native_window"]["usage_percentage"] == 0
    assert account["weekly_window"]["usage_percentage"] == 78
    assert account["isActive"] is True
    assert list(profile.glob(".credentials.json.bak-*"))


def test_claude_failed_fetch_does_not_turn_local_history_into_quota(tmp_path, monkeypatch):
    from tests.test_refresh import make_profile
    profile = make_profile(tmp_path, "claude", "one", token="valid", ident="same")
    directory = tmp_path / "profiles" / "claude" / "one"
    (directory / "history.jsonl").write_text(json.dumps({"timestamp": NOW.isoformat()}) + "\n")
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": [profile]}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: (_ for _ in ()).throw(http_error(401)))
    status = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["claude"])
    account = status["agents"]["claude"]["accounts"][0]
    assert account["no_data"] is True
    assert account["native_window"]["usage_percentage"] is None
    assert account["weekly_window"]["usage_percentage"] is None
    assert account["native_window"]["tokens_used"] == 0


@pytest.mark.parametrize("system_identity", [None, "different"])
def test_identity_unknown_or_divergent_never_copies_system_credential(tmp_path, monkeypatch, system_identity):
    from tests.test_refresh import make_profile
    profile = make_profile(tmp_path, "claude", "one", token="old", ident="same")
    system = tmp_path / "system"
    system.mkdir()
    (system / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "new", "expiresAt": 2_000_000_000_000}}))
    if system_identity:
        (system / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": system_identity}}))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(system / ".credentials.json"))
    profile_file = profile["credential_path"]
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": [profile]}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: FakeHttp(claude=[{
        "five_hour": {"utilization": 5}, "seven_day": {"utilization": 10},
    }])(req, timeout))
    collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["claude"])
    assert json.loads(Path(profile_file).read_text())["claudeAiOauth"]["accessToken"] == "old"


def test_partial_claude_api_response_has_only_confirmed_window(tmp_path, monkeypatch):
    from tests.test_refresh import make_profile
    profile = make_profile(tmp_path, "claude", "one", token="valid", ident="same")
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": [profile]}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: FakeHttp(claude=[{
        "five_hour": {"utilization": 0}, "seven_day": None,
    }])(req, timeout))
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["claude"])["agents"]["claude"]["accounts"][0]
    assert account["native_window"]["usage_percentage"] == 0
    assert account["weekly_window"]["usage_percentage"] is None
    assert "no_data" not in account


def test_partial_new_response_does_not_mark_confirmed_window_stale(tmp_path, monkeypatch):
    from tests.test_refresh import make_profile
    profile = make_profile(tmp_path, "claude", "one", token="valid", ident="same")
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": [profile]}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config)
    http = FakeHttp(claude=[
        {"five_hour": {"utilization": 20}, "seven_day": {"utilization": 70}},
        {"five_hour": {"utilization": 30}, "seven_day": None},
    ])
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: http(req, timeout))
    cache = tmp_path / "status.json"
    collect_and_save(config, cache, now=NOW, providers=["claude"])
    later = NOW.replace(hour=13)
    account = collect_and_save(config, cache, now=later, providers=["claude"])["agents"]["claude"]["accounts"][0]
    assert account["native_window"]["usage_percentage"] == 30
    assert account["weekly_window"]["usage_percentage"] is None
    assert account["fetched_at"] == later.isoformat()
    assert account["stale"] is False


def test_missing_profile_credential_is_restored_when_identity_remains(tmp_path, monkeypatch):
    from tests.test_refresh import make_profile
    profile = make_profile(tmp_path, "claude", "one", token="old", ident="same")
    Path(profile["credential_path"]).unlink()
    system = tmp_path / "system"
    system.mkdir()
    (system / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "same"}}))
    (system / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "new", "expiresAt": 2_000_000_000_000}}))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(system / ".credentials.json"))
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: FakeHttp(claude=[{
        "five_hour": {"utilization": 12}, "seven_day": {"utilization": 34},
    }])(req, timeout))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": [profile]}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config)
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["claude"])["agents"]["claude"]["accounts"][0]
    assert json.loads(Path(profile["credential_path"]).read_text())["claudeAiOauth"]["accessToken"] == "new"
    assert account["native_window"]["usage_percentage"] == 12
