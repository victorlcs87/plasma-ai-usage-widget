"""Coleta pública depois de um novo login no Codex CLI."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector import renew
from ai_usage_collector.config import save_config
from tests.test_refresh import FakeHttp, http_error, make_profile


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def _setup(tmp_path, monkeypatch, system_id="same", profile_id="same", system_refresh="2026-10-24T11:00:00Z", profile_refresh="2026-10-23T11:00:00Z"):
    profile = make_profile(tmp_path, "codex", "one", token="old", ident=profile_id)
    profile_file = Path(profile["credential_path"])
    old = json.loads(profile_file.read_text())
    old["last_refresh"] = profile_refresh
    profile_file.write_text(json.dumps(old))
    system = tmp_path / "system"
    system.mkdir()
    system_file = system / "auth.json"
    system_file.write_text(json.dumps({"auth_mode": "chatgpt", "last_refresh": system_refresh,
                                      "tokens": {"account_id": system_id, "access_token": "new", "refresh_token": "new-r"}}))
    monkeypatch.setenv("CODEX_HOME", str(system))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": [profile]}, "gemini": {"accounts": []}}}, config)
    return config, profile_file


@pytest.mark.parametrize("system_refresh,expected", [
    ("2026-10-24T11:00:00Z", "new"),
    ("2026-10-22T11:00:00Z", "old"),
])
def test_new_login_syncs_same_identity_without_regression(tmp_path, monkeypatch, system_refresh, expected):
    config, profile_file = _setup(tmp_path, monkeypatch, system_refresh=system_refresh)
    http = FakeHttp(codex=[{"rate_limit": {"primary_window": {"used_percent": 0},
                                            "secondary_window": {"used_percent": 70}}}])
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: http(req, timeout))
    monkeypatch.setattr("urllib.request.urlopen", http)
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["codex"])["agents"]["codex"]["accounts"][0]
    assert json.loads(profile_file.read_text())["tokens"]["access_token"] == expected
    assert account["isActive"] is True
    assert account["native_window"]["usage_percentage"] == 0
    assert account["weekly_window"]["usage_percentage"] == 70
    assert list(profile_file.parent.glob("auth.json.bak-*"))


@pytest.mark.parametrize("system_id", [None, "different"])
def test_unknown_or_divergent_identity_does_not_copy(tmp_path, monkeypatch, system_id):
    config, profile_file = _setup(tmp_path, monkeypatch, system_id=system_id)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: FakeHttp(codex=[{"rate_limit": {"primary_window": {"used_percent": 15}}}])(req, timeout))
    monkeypatch.setattr("urllib.request.urlopen", FakeHttp(codex=[{"rate_limit": {"primary_window": {"used_percent": 15}}}]))
    collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["codex"])
    assert json.loads(profile_file.read_text())["tokens"]["access_token"] == "old"


def test_failed_quota_preserves_history_without_false_zero(tmp_path, monkeypatch):
    config, profile_file = _setup(tmp_path, monkeypatch)
    (profile_file.parent / "history.jsonl").write_text(json.dumps({"ts": NOW.timestamp() - 30, "text": "prompt"}) + "\n")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: (_ for _ in ()).throw(http_error(429, "120")))
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: (_ for _ in ()).throw(http_error(429, "120")))
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["codex"])["agents"]["codex"]["accounts"][0]
    assert account["no_data"] is True
    assert account["native_window"]["usage_percentage"] is None
    assert account["native_window"]["messages_used"] == 1
    assert account["fetch_error"]["kind"] == "rate_limited"
    assert "renewal" not in account


def test_failed_quota_uses_stale_cache_for_same_identity(tmp_path, monkeypatch):
    config, profile_file = _setup(tmp_path, monkeypatch)
    http = FakeHttp(codex=[{"rate_limit": {"primary_window": {"used_percent": 25},
                                            "secondary_window": {"used_percent": 60}}}, http_error(429, "120")])
    monkeypatch.setattr("urllib.request.urlopen", http)
    cache = tmp_path / "status.json"
    collect_and_save(config, cache, now=NOW, providers=["codex"])
    account = collect_and_save(config, cache, now=NOW.replace(hour=13), providers=["codex"])["agents"]["codex"]["accounts"][0]
    assert account["native_window"]["usage_percentage"] == 25
    assert account["weekly_window"]["usage_percentage"] == 60
    assert account["stale"] is True
    assert account["fetched_at"] == NOW.isoformat()
    assert "no_data" not in account


def test_partial_response_does_not_infer_other_window(tmp_path, monkeypatch):
    config, _ = _setup(tmp_path, monkeypatch)
    http = FakeHttp(codex=[{"rate_limit": {"primary_window": {"used_percent": 0}}}])
    monkeypatch.setattr("urllib.request.urlopen", http)
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["codex"])["agents"]["codex"]["accounts"][0]
    assert account["native_window"]["usage_percentage"] == 0
    assert account["weekly_window"]["usage_percentage"] is None
    assert "no_data" not in account


def test_auth_rejection_retries_once_after_safe_renewal(tmp_path, monkeypatch):
    config, profile_file = _setup(tmp_path, monkeypatch)
    system_file = tmp_path / "system" / "auth.json"
    http = FakeHttp(codex=[http_error(401), {"rate_limit": {"primary_window": {"used_percent": 30}}}])
    monkeypatch.setattr("urllib.request.urlopen", http)
    calls = []
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"codex": False})
    def fake_renewer(_directory):
        calls.append(True)
        data = json.loads(system_file.read_text())
        data["tokens"]["access_token"] = "renewed"
        data["last_refresh"] = "2026-10-24T11:30:00Z"
        system_file.write_text(json.dumps(data))
    monkeypatch.setitem(renew.RENEWERS, "codex", fake_renewer)
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["codex"])["agents"]["codex"]["accounts"][0]
    assert len(calls) == 1
    assert http.calls["codex"] == 2
    assert account["native_window"]["usage_percentage"] == 30
    assert json.loads(profile_file.read_text())["tokens"]["access_token"] == "renewed"
    assert list(profile_file.parent.glob("auth.json.bak-*"))


@pytest.mark.parametrize("running", [True, None])
def test_active_cli_or_unknown_process_state_blocks_renewal(tmp_path, monkeypatch, running):
    config, profile_file = _setup(tmp_path, monkeypatch)
    before = profile_file.read_bytes()
    http = FakeHttp(codex=[http_error(401)])
    monkeypatch.setattr("urllib.request.urlopen", http)
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"codex": running})
    calls = []
    monkeypatch.setitem(renew.RENEWERS, "codex", lambda _directory: calls.append(True))
    account = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["codex"])["agents"]["codex"]["accounts"][0]
    assert calls == []
    assert http.calls["codex"] == 1
    assert profile_file.read_bytes() != before  # a sincronização inicial ainda é segura
    assert account["no_data"] is True
    assert account["renewal"]["error"] == ("cli_running" if running else "detection_failed")
