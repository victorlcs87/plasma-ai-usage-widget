"""Recuperação da Conta Ativa Claude na coleta pública."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_usage_collector import renew
from test_refresh import API_OK, T0, FakeHttp, acc_of, configure, env, http_error, make_profile
from test_renew import install_system


def setup_active(env, tmp_path):
    account = make_profile(tmp_path, "claude", "one", ident="same")
    system = install_system(tmp_path, "claude", account, ident="same")
    configure(env, tmp_path, {"claude": [account]})
    return account, system


def rotate(system):
    path = system / ".credentials.json"
    data = json.loads(path.read_text())
    data["claudeAiOauth"].update(accessToken="rotated", expiresAt=(T0 + timedelta(hours=8)).isoformat())
    path.write_text(json.dumps(data))


def test_rejected_active_token_renews_and_retries_once(env, tmp_path, monkeypatch):
    account, system = setup_active(env, tmp_path)
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"claude": False})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": lambda profile: (calls.append(profile), rotate(profile))})
    http = FakeHttp(claude=[http_error(401), API_OK["claude"]])
    status = env["run"]("--provider", "claude", http=http)
    result = acc_of(status, "claude")
    assert calls == [system]
    assert http.calls["claude"] == 2
    assert result["renewal"]["error"] is None
    assert result["native_window"]["usage_percentage"] == 42
    assert json.loads(Path(account["credential_path"]).read_text())["claudeAiOauth"]["accessToken"] == "rotated"
    assert list(Path(account["credential_path"]).parent.glob(".credentials.json.bak-*"))


@pytest.mark.parametrize("running,expected", [(True, "cli_running"), (None, "detection_failed")])
def test_rejected_token_does_not_touch_unsafe_cli(env, tmp_path, monkeypatch, running, expected):
    account, system = setup_active(env, tmp_path)
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"claude": running})
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": calls.append})
    http = FakeHttp(claude=[http_error(401)])
    status = env["run"]("--provider", "claude", http=http)
    assert calls == []
    assert http.calls["claude"] == 1
    assert acc_of(status, "claude")["renewal"]["error"] == expected
    assert acc_of(status, "claude")["no_data"] is True
    assert json.loads((system / ".credentials.json").read_text()) == json.loads(Path(account["credential_path"]).read_text())


def test_network_failure_does_not_renew_active_account(env, tmp_path, monkeypatch):
    setup_active(env, tmp_path)
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": calls.append})
    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[http_error(429)]))
    assert calls == []
    assert acc_of(status, "claude")["fetch_error"]["kind"] == "rate_limited"


def test_valid_token_near_expiry_does_not_renew_before_fetch(env, tmp_path, monkeypatch):
    account, system = setup_active(env, tmp_path)
    data = json.loads((system / ".credentials.json").read_text())
    data["claudeAiOauth"]["expiresAt"] = (T0 + timedelta(minutes=2)).isoformat()
    (system / ".credentials.json").write_text(json.dumps(data))
    Path(account["credential_path"]).write_text(json.dumps(data))
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": calls.append})
    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))
    assert calls == []
    assert acc_of(status, "claude")["native_window"]["usage_percentage"] == 42


def test_gateway_auth_failure_does_not_renew_oauth(env, tmp_path, monkeypatch):
    setup_active(env, tmp_path)
    config = json.loads(env["config"].read_text())
    config["agents"]["claude"].update(api_base_url="https://api.anthropic.com", api_key="gateway-key")
    env["config"].write_text(json.dumps(config))
    calls = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": calls.append})
    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[http_error(401)]))
    assert calls == []
    assert acc_of(status, "claude")["fetch_error"]["kind"] == "auth"


def test_failed_renewal_is_limited_to_one_attempt_per_interval(env, tmp_path, monkeypatch):
    setup_active(env, tmp_path)
    monkeypatch.setattr("ai_usage_collector.running.detect_running", lambda: {"claude": False})
    calls = []
    def fail(profile):
        calls.append(profile)
        raise renew.RenewError("revoked")
    monkeypatch.setattr(renew, "RENEWERS", {"claude": fail})
    first = env["run"]("--provider", "claude", http=FakeHttp(claude=[http_error(401)]))
    second = env["run"]("--provider", "claude", http=FakeHttp(claude=[http_error(401)]))
    assert len(calls) == 1
    assert acc_of(first, "claude")["renewal"]["error"] == "revoked"
    assert acc_of(second, "claude")["renewal"]["error"] == "revoked"
    assert acc_of(second, "claude")["no_data"] is True
