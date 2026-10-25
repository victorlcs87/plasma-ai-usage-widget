"""Account-scoped manual renewal: provider isolation, active-session guards and usage refresh."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_usage_collector import renew
from ai_usage_collector.cli import main
from test_refresh import API_OK, T0, FakeHttp, acc_of, configure, env, http_error, make_profile
from test_renew import install_system


def refresh_fake(provider, calls):
    def run(profile):
        calls.append(profile)
        file = profile / {"claude": ".credentials.json", "codex": "auth.json", "gemini": "oauth_creds.json"}[provider]
        data = json.loads(file.read_text())
        if provider == "claude":
            data["claudeAiOauth"]["expiresAt"] = (T0 + timedelta(hours=8)).isoformat()
        elif provider == "gemini":
            data["expiry_date"] = int((T0 + timedelta(hours=1)).timestamp() * 1000)
        file.write_text(json.dumps(data))
    return run


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini"])
def test_manual_renew_only_targets_requested_account_and_fetches_usage(env, tmp_path, monkeypatch, provider):
    target = make_profile(tmp_path, provider, "target", expired=True, ident="one@example.test")
    other = make_profile(tmp_path, provider, "other", ident="two@example.test")
    configure(env, tmp_path, {provider: [target, other]})
    env["run"]("--provider", provider, http=FakeHttp(**{provider: [API_OK[provider]]}))
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {provider: refresh_fake(provider, calls)})
    status = env["run"]("--renew-account", provider, "target", http=FakeHttp(**{provider: [API_OK[provider]]}))
    assert calls == [Path(target[provider + "_dir"]) ]
    assert acc_of(status, provider)["native_window"]["usage_percentage"] == 42.0
    assert acc_of(status, provider)["renewal"]["error"] is None
    assert status["agents"][provider]["accounts"][1]["id"] == "other"
    assert "renewal" not in status["agents"][provider]["accounts"][1]


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_manual_active_renew_uses_system_cli_then_updates_isolated_copy(env, tmp_path, monkeypatch, provider):
    target = make_profile(tmp_path, provider, "target", expired=True, ident="identity")
    system = install_system(tmp_path, provider, target, ident="identity")
    configure(env, tmp_path, {provider: [target]})
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {provider: False})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {provider: refresh_fake(provider, calls)})
    status = env["run"]("--renew-account", provider, "target", http=FakeHttp(**{provider: [API_OK[provider]]}))
    assert calls == [system]
    account = acc_of(status, provider)
    assert account["isActive"] is True
    assert account["renewal"]["error"] is None
    assert account["native_window"]["usage_percentage"] == 42.0
    assert json.loads(Path(target["credential_path"]).read_text()) == json.loads((system / Path(target["credential_path"]).name).read_text())


@pytest.mark.parametrize("running", [True, None])
def test_manual_active_renew_does_not_touch_a_running_or_unknown_cli(env, tmp_path, monkeypatch, running):
    target = make_profile(tmp_path, "claude", "target", expired=True, ident="identity")
    install_system(tmp_path, "claude", target, ident="identity")
    configure(env, tmp_path, {"claude": [target]})
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"claude": running})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": refresh_fake("claude", calls)})
    status = env["run"]("--renew-account", "claude", "target", http=FakeHttp(claude=[API_OK["claude"]]))
    assert calls == []
    assert acc_of(status, "claude")["renewal"]["error"] == ("cli_running" if running else "detection_failed")


def test_unknown_account_is_rejected_without_creating_status(env, tmp_path, capsys):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "known")]})
    code = main(["--config-path", str(env["config"]), "--cache-path", str(env["cache"]),
                 "--renew-account", "claude", "unknown"])
    assert code == 2
    assert not env["cache"].exists()


@pytest.mark.parametrize("storage", ["flat", "nested", "keyring"])
def test_manual_active_gemini_refreshes_authoritative_store_and_copy(env, tmp_path, monkeypatch, storage):
    target = make_profile(tmp_path, "gemini", "target", expired=True, ident="demo@example.test")
    system_dir = install_system(tmp_path, "gemini", target)
    system_file = system_dir / "oauth_creds.json"
    old = json.loads(system_file.read_text())
    original = {"auth_method": "consumer", "token": old} if storage == "nested" else old
    system_file.write_text(json.dumps(original))
    stored = []
    source = "keyring (secret-tool)" if storage == "keyring" else str(system_file)
    monkeypatch.setattr("ai_usage_collector.capture.get_active_gemini_credentials", lambda _override=None: (old, source))
    monkeypatch.setattr("ai_usage_collector.capture._store_gemini_keyring", stored.append)
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"gemini": False})
    new = {**old, "access_token": "refreshed", "expiry_date": int((T0 + timedelta(hours=1)).timestamp() * 1000)}
    monkeypatch.setattr(renew, "_refresh_gemini_credentials", lambda _creds: new)
    configure(env, tmp_path, {"gemini": [target]})
    status = env["run"]("--renew-account", "gemini", "target", http=FakeHttp(gemini=[API_OK["gemini"]]))
    assert acc_of(status, "gemini")["isActive"]
    assert acc_of(status, "gemini")["renewal"]["error"] is None
    assert acc_of(status, "gemini")["native_window"]["usage_percentage"] == 42.0
    assert json.loads(Path(target["credential_path"]).read_text())["access_token"] == "refreshed"
    if storage == "keyring":
        assert stored == [new]
    else:
        saved = json.loads(system_file.read_text())
        assert (saved["token"] if storage == "nested" else saved)["access_token"] == "refreshed"
        if storage == "nested":
            assert saved["auth_method"] == "consumer"


def test_manual_gemini_renewal_does_not_enable_automatic_renewal(env, tmp_path, monkeypatch):
    target = make_profile(tmp_path, "gemini", "target", expired=True)
    configure(env, tmp_path, {"gemini": [target]})
    config = json.loads(env["config"].read_text())
    config["renew"]["gemini"] = False
    env["config"].write_text(json.dumps(config))
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"gemini": refresh_fake("gemini", calls)})
    status = env["run"]("--renew-account", "gemini", "target", http=FakeHttp(gemini=[API_OK["gemini"]]))
    assert calls == [Path(target["gemini_dir"])]
    assert acc_of(status, "gemini")["renewal"]["error"] is None
    assert json.loads(env["config"].read_text())["renew"]["gemini"] is False


def test_manual_renew_preserves_requested_refresh_interval(env, tmp_path, monkeypatch):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "target", expired=True)]})
    monkeypatch.setattr(renew, "RENEWERS", {"claude": refresh_fake("claude", [])})
    status = env["run"]("--renew-account", "claude", "target", "--refresh-interval", "claude=7200",
                        http=FakeHttp(claude=[API_OK["claude"]]))
    assert acc_of(status, "claude")["next_check_at"] == (T0 + timedelta(hours=2)).isoformat()


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_manually_configured_system_account_can_renew_without_isolated_copy(env, tmp_path, monkeypatch, provider):
    account = make_profile(tmp_path, provider, "system", expired=True, ident="identity")
    system = install_system(tmp_path, provider, account, ident="identity")
    account["credential_path"] = str(system / Path(account["credential_path"]).name)
    account[provider + "_dir"] = str(system)
    configure(env, tmp_path, {provider: [account]})
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {provider: False})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {provider: refresh_fake(provider, calls)})
    status = env["run"]("--renew-account", provider, "system", http=FakeHttp(**{provider: [API_OK[provider]]}))
    assert calls == [system]
    assert acc_of(status, provider)["renewal"]["error"] is None
    assert acc_of(status, provider)["native_window"]["usage_percentage"] == 42.0


def test_manual_renew_uses_credential_directory_when_provider_directory_is_absent(env, tmp_path, monkeypatch):
    target = make_profile(tmp_path, "claude", "target", expired=True)
    profile = Path(target.pop("claude_dir"))
    configure(env, tmp_path, {"claude": [target]})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": refresh_fake("claude", calls)})
    status = env["run"]("--renew-account", "claude", "target", http=FakeHttp(claude=[API_OK["claude"]]))
    assert calls == [profile]
    assert acc_of(status, "claude")["renewal"]["error"] is None


def test_manual_renew_cannot_bypass_shared_system_refresh_token_guard(env, tmp_path, monkeypatch):
    from test_renew_safety import profile_with_refresh, system_with_refresh
    system_with_refresh(tmp_path, "SHARED-TEST", ident="system")
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"claude": False})
    target = profile_with_refresh(tmp_path, "target", "SHARED-TEST", ident="other")
    configure(env, tmp_path, {"claude": [target]})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": calls.append})
    status = env["run"]("--renew-account", "claude", "target", http=FakeHttp(claude=[API_OK["claude"]]))
    assert calls == []
    assert acc_of(status, "claude")["renewal"]["error"] == "detection_failed"


@pytest.mark.parametrize("storage", ["keyring", "file"])
def test_manual_active_gemini_rejects_divergent_identity_without_persisting(env, tmp_path, monkeypatch, storage):
    target = make_profile(tmp_path, "gemini", "target", expired=True, ident="demo@example.test")
    system_dir = install_system(tmp_path, "gemini", target)
    system_file = system_dir / "oauth_creds.json"
    old = json.loads(system_file.read_text())
    stored = []
    source = "keyring (secret-tool)" if storage == "keyring" else str(system_file)
    monkeypatch.setattr("ai_usage_collector.capture.get_active_gemini_credentials", lambda _override=None: (old, source))
    monkeypatch.setattr("ai_usage_collector.capture._store_gemini_keyring", stored.append)
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"gemini": False})
    # Credencial renovada com identidade divergente (outro email)
    divergent = {**old, "email": "divergent@example.test", "access_token": "divergent-tok"}
    divergent.pop("id_token", None)
    monkeypatch.setattr(renew, "_refresh_gemini_credentials", lambda _creds: divergent)
    configure(env, tmp_path, {"gemini": [target]})
    status = env["run"]("--renew-account", "gemini", "target", http=FakeHttp(gemini=[API_OK["gemini"]]))
    assert acc_of(status, "gemini")["renewal"]["error"] == "detection_failed"
    assert stored == []
    assert json.loads(system_file.read_text())["access_token"] == old["access_token"]


def test_manual_active_claude_renewal_with_http_429_records_pause_without_retry(env, tmp_path, monkeypatch):
    target = make_profile(tmp_path, "claude", "target", expired=True, ident="identity")
    system = install_system(tmp_path, "claude", target, ident="identity")
    configure(env, tmp_path, {"claude": [target]})
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"claude": False})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": refresh_fake("claude", calls)})
    status = env["run"]("--renew-account", "claude", "target", http=FakeHttp(claude=[http_error(429, "120")]))
    assert calls == [system]
    account = acc_of(status, "claude")
    assert account["renewal"]["error"] is None
    assert account["fetch_error"]["kind"] == "rate_limited"
    assert account["fetch_error"]["retry_at"] is not None
    assert account["native_window"]["usage_percentage"] is None
    assert account["no_data"] is True
    # Credencial foi renovada
    assert json.loads(Path(target["credential_path"]).read_text())["claudeAiOauth"]["expiresAt"] > (T0 + timedelta(hours=1)).isoformat()
