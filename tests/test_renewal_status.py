"""Resultado classificado da ultima renovacao no status.json, por Conta (Spec 08, ticket 61)."""

import json
from datetime import timedelta

import pytest

from ai_usage_collector import renew
from ai_usage_collector.contract import validate_status_contract
from test_refresh import FakeHttp, T0, acc_of, configure, env, http_error, make_profile  # noqa: F401


def _failing(code):
    def renewer(_profile):
        if code:
            raise renew.RenewError(code)
    return renewer


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini"])
@pytest.mark.parametrize("code", ["revoked", "cli_missing", "timeout", None])
def test_last_renewal_result_is_exposed_without_secrets(env, tmp_path, monkeypatch, provider, code):
    monkeypatch.setattr(renew, "RENEWERS", {provider: _failing(code)})
    configure(env, tmp_path, {provider: [make_profile(tmp_path, provider, "a", token="SEGREDO-XYZ", expired=timedelta(minutes=30))]})

    status = env["run"]("--provider", provider, http=FakeHttp(**{provider: [http_error(401)]}))

    acc = acc_of(status, provider)
    assert acc["fetch_error"]["kind"] == "auth"
    assert acc["renewal"] == {"error": code, "at": T0.isoformat()}
    assert "SEGREDO-XYZ" not in json.dumps(status)


def test_renewal_is_kept_inside_the_interval_and_absent_without_attempt(env, tmp_path, monkeypatch):
    monkeypatch.setattr(renew, "RENEWERS", {"claude": _failing("timeout")})
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a", expired=timedelta(minutes=30))]})
    http = FakeHttp(claude=[http_error(401)])
    env["run"]("--provider", "claude", http=http)
    env["clock"]["now"] = T0 + timedelta(minutes=30)
    acc = acc_of(env["run"]("--provider", "claude", http=http), "claude")
    assert acc["renewal"] == {"error": "timeout", "at": T0.isoformat()}  # nao tentou de novo, mas informa a ultima

    monkeypatch.setattr(renew, "RENEWERS", {})
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "b", expired=timedelta(minutes=30))]})
    assert "renewal" not in acc_of(env["run"]("--provider", "claude", http=http), "claude")


def test_contract_accepts_old_payload_and_rejects_malformed_renewal():
    from ai_usage_collector.contract import build_agent_account_status

    def payload(**extra):
        accs = lambda p: [{**build_agent_account_status(provider=p, account_id="a", label="A", source="auto", health={"status": "valid"}, native_window=None, weekly_window=None), **extra}]
        return {"version": 5, "last_updated": "2026-10-20T15:00:00+00:00", "status": "ok", "agents": {p: {"name": p, "status": "ok", "accounts": accs(p)} for p in ("claude", "codex", "gemini")}}

    assert validate_status_contract(payload()) is True
    assert validate_status_contract(payload(renewal={"error": None, "at": "2026-10-20T15:00:00+00:00"})) is True
    assert validate_status_contract(payload(renewal="x")) is False
