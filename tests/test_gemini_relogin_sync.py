"""Coleta Gemini com credenciais sintéticas após novo login."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_usage_collector import renew
from ai_usage_collector import capture
from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.config import load_config, save_config
from tests.test_refresh import FakeHttp, http_error, make_profile


NOW = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
QUOTA = {"buckets": [{"bucketId": "gemini-5h", "remainingFraction": 1.0}]}


@pytest.mark.parametrize("system_expiry,profile_expiry,expected", [
    (2_000_000_000_000, 1_800_000_000_000, "new"),
    (1_800_000_000_000, 2_000_000_000_000, "old"),
])
def test_collect_syncs_gemini_identity_with_backup_and_no_regression(
    tmp_path, monkeypatch, system_expiry, profile_expiry, expected,
):
    account = make_profile(tmp_path, "gemini", "one", ident="one@example.test")
    profile = Path(account["credential_path"])
    profile.write_text(json.dumps({"email": "one@example.test", "access_token": "old", "refresh_token": "r-old", "expiry_date": profile_expiry}))
    system = tmp_path / "system.json"
    system.write_text(json.dumps({"email": "one@example.test", "access_token": "new", "refresh_token": "r-new", "expiry_date": system_expiry}))
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", str(system))
    monkeypatch.setattr("urllib.request.urlopen", FakeHttp(gemini=[QUOTA]))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [account]}}, "renew": {"gemini": False}}, config)
    profile = Path(load_config(config)["agents"]["gemini"]["accounts"][0]["credential_path"])

    result = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])

    assert json.loads(profile.read_text())["access_token"] == expected
    assert list(profile.parent.glob("oauth_creds.json.bak-*"))
    assert result["agents"]["gemini"]["accounts"][0]["isActive"] is True
    assert result["agents"]["gemini"]["accounts"][0]["native_window"]["usage_percentage"] == 0


@pytest.mark.parametrize("system_email", [None, "other@example.test"])
def test_collect_never_copies_unmatched_gemini_identity(tmp_path, monkeypatch, system_email):
    account = make_profile(tmp_path, "gemini", "one", ident="one@example.test")
    profile = Path(account["credential_path"])
    system = tmp_path / "system.json"
    system.write_text(json.dumps({"email": system_email, "access_token": "new", "expiry_date": 2_000_000_000_000}))
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", str(system))
    monkeypatch.setattr("urllib.request.urlopen", FakeHttp(gemini=[QUOTA]))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [account]}}, "renew": {"gemini": False}}, config)
    profile = Path(load_config(config)["agents"]["gemini"]["accounts"][0]["credential_path"])

    collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])

    assert json.loads(profile.read_text())["access_token"] == "tok-1"


def test_collect_syncs_matching_keyring_payload(tmp_path, monkeypatch):
    account = make_profile(tmp_path, "gemini", "one", ident="one@example.test")
    account["source"] = "captured"
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [account]}}, "renew": {"gemini": False}}, config)
    profile = Path(load_config(config)["agents"]["gemini"]["accounts"][0]["credential_path"])
    monkeypatch.setattr(capture, "get_active_gemini_credentials", lambda override=None: (
        {"email": "one@example.test", "token": {"access_token": "keyring-new", "refresh_token": "keyring-r", "expiry_date": 2_000_000_000_000}},
        "keyring (secret-tool)",
    ))
    monkeypatch.setattr(
        "ai_usage_collector.collector.sync_gemini_from_antigravity",
        lambda _path: pytest.fail("Antigravity must not replace the active keyring credential"),
    )
    monkeypatch.setattr("urllib.request.urlopen", FakeHttp(gemini=[QUOTA]))

    entry = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])["agents"]["gemini"]["accounts"][0]

    assert json.loads(profile.read_text())["access_token"] == "keyring-new"
    assert entry["isActive"] is True


def test_ambiguous_gemini_identity_preserves_both_profiles(tmp_path, monkeypatch):
    first = make_profile(tmp_path, "gemini", "one", token="first", ident="same@example.test")
    second = make_profile(tmp_path, "gemini", "two", token="second", ident="same@example.test")
    second_path = Path(second["credential_path"])
    second_data = json.loads(second_path.read_text())
    second_data["refresh_token"] = "r-second"
    second_path.write_text(json.dumps(second_data))
    system = tmp_path / "system.json"
    system.write_text(json.dumps({"email": "same@example.test", "access_token": "new", "refresh_token": "r-new", "expiry_date": 2_000_000_000_000}))
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", str(system))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [first, second]}}, "renew": {"gemini": False}}, config)
    profiles = [Path(a["credential_path"]) for a in load_config(config)["agents"]["gemini"]["accounts"]]
    assert len(profiles) == 2
    before = [p.read_bytes() for p in profiles]
    monkeypatch.setattr("urllib.request.urlopen", FakeHttp(gemini=[QUOTA]))

    collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])

    assert [p.read_bytes() for p in profiles] == before


def test_opt_out_never_uses_gemini_oauth(tmp_path, monkeypatch):
    account = make_profile(tmp_path, "gemini", "one", ident="one@example.test", expired=True)
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", account["credential_path"])
    monkeypatch.setattr(renew, "_agy_binary", lambda: pytest.fail("OAuth opt-in accessed"))
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [account]}}, "renew": {"gemini": False}}, config)
    result = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])
    entry = result["agents"]["gemini"]["accounts"][0]
    assert result["renew"]["gemini"] is False
    assert entry["renewal"]["error"] == "disabled"
    assert entry["no_data"] is True


def test_opt_in_expired_active_account_attempts_safe_renewal(tmp_path, monkeypatch):
    account = make_profile(tmp_path, "gemini", "one", ident="one@example.test", expired=True)
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", account["credential_path"])
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [account]}}, "renew": {"gemini": True}}, config)
    attempts = []
    monkeypatch.setattr(renew, "renew_active_auto", lambda *args, **kwargs: attempts.append(args[1:3]) or False)

    result = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])

    assert attempts == [("gemini", "one")]
    assert result["renew"]["gemini"] is True


def test_auth_rejection_renews_once_and_retries_quota(tmp_path, monkeypatch):
    account = make_profile(tmp_path, "gemini", "one", ident="one@example.test")
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", account["credential_path"])
    config = tmp_path / "config.json"
    save_config({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": [account]}}, "renew": {"gemini": True}}, config)
    active_profile = Path(load_config(config)["agents"]["gemini"]["accounts"][0]["credential_path"])
    http = FakeHttp(gemini=[http_error(401), http_error(401), QUOTA, QUOTA])
    monkeypatch.setattr("urllib.request.urlopen", http)
    attempts = []

    def safe_renew(*args, **kwargs):
        attempts.append(http.calls["gemini"])
        profile = active_profile
        updated = json.loads(profile.read_text())
        updated["access_token"] = "renewed"
        profile.write_text(json.dumps(updated))
        return True

    monkeypatch.setattr(renew, "renew_active_auto", safe_renew)
    entry = collect_and_save(config, tmp_path / "status.json", now=NOW, providers=["gemini"])["agents"]["gemini"]["accounts"][0]

    assert attempts == [2]
    assert http.calls["gemini"] == 4
    assert json.loads(active_profile.read_text())["access_token"] == "renewed"
    assert entry["native_window"]["usage_percentage"] == 0
