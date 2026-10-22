"""Renovacao de Conta inativa pela CLI (Spec 08, ticket 57): Claude, `claude auth status` no Perfil Isolado."""

import json
import stat
import subprocess
from datetime import timedelta

import pytest

from ai_usage_collector import renew
REAL_RENEWERS = dict(renew.RENEWERS)
from test_refresh import API_OK, T0, FakeHttp, acc_of, configure, env, make_profile  # noqa: F401

FAKE_CLAUDE = """#!/bin/sh
echo "$CLAUDE_CONFIG_DIR|$*" >> "{log}"
[ -n "{fail}" ] && exit 1
cat > "$CLAUDE_CONFIG_DIR/.credentials.json" <<EOF
{{"claudeAiOauth": {{"accessToken": "tok-renovado", "expiresAt": "{future}"}}}}
EOF
"""


def expire(profile):
    cred = profile["credential_path"]
    data = json.loads(open(cred).read())
    data["claudeAiOauth"]["expiresAt"] = (T0 - timedelta(hours=40)).isoformat()
    open(cred, "w").write(json.dumps(data))


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "claude_calls.log"

    def install(fail=False):
        exe = bin_dir / "claude"
        exe.write_text(FAKE_CLAUDE.format(log=log, fail="1" if fail else "", future=(T0 + timedelta(hours=8)).isoformat()))
        exe.chmod(0o755)

    install()
    monkeypatch.setattr(renew, "RENEWERS", REAL_RENEWERS)  # o conftest zera os renovadores por padrao
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    calls = lambda: log.read_text().splitlines() if log.exists() else []  # noqa: E731
    return type("F", (), {"install": staticmethod(install), "calls": staticmethod(calls), "dir": bin_dir})


def test_expired_inactive_profile_is_renewed_and_usage_shown(env, tmp_path, fake_claude):
    prof = make_profile(tmp_path, "claude", "cga")
    expire(prof)
    configure(env, tmp_path, {"claude": [prof]})
    http = FakeHttp(claude=[API_OK["claude"]])

    status = env["run"]("--provider", "claude", http=http)

    assert fake_claude.calls() == [f"{prof['claude_dir']}|auth status"]
    acc = acc_of(status, "claude")
    assert acc["native_window"]["usage_percentage"] == 42.0
    assert "fetch_error" not in acc


def test_active_system_account_is_never_renewed(env, tmp_path, fake_claude):
    active = make_profile(tmp_path, "claude", "ativa", token="tok-ativa")
    other = make_profile(tmp_path, "claude", "outra", token="tok-outra")
    sys_dir = tmp_path / "_sys_claude"
    sys_dir.mkdir()
    (sys_dir / ".credentials.json").write_text(open(active["credential_path"]).read())
    configure(env, tmp_path, {"claude": [active, other]})

    env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    assert fake_claude.calls() == [f"{other['claude_dir']}|auth status"]


def test_at_most_one_renewal_per_account_per_interval(env, tmp_path, fake_claude):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    http = FakeHttp(claude=[API_OK["claude"]])
    env["run"]("--provider", "claude", http=http)
    env["clock"]["now"] = T0 + timedelta(minutes=30)
    env["run"](http=http)  # "Atualizar agora" dentro do intervalo
    assert len(fake_claude.calls()) == 1

    env["clock"]["now"] = T0 + timedelta(hours=1, seconds=1)
    env["run"](http=http)
    assert len(fake_claude.calls()) == 2


def test_missing_cli_does_not_break_cycle_and_is_classified(env, tmp_path, fake_claude, capsys):
    (fake_claude.dir / "claude").unlink()
    a, b = make_profile(tmp_path, "claude", "a"), make_profile(tmp_path, "claude", "b")
    configure(env, tmp_path, {"claude": [a, b]})

    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    assert [x["native_window"]["usage_percentage"] for x in status["agents"]["claude"]["accounts"]] == [42.0, 42.0]
    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["claude:a"]["error"] == "cli_missing"
    assert "cli_missing" in capsys.readouterr().err


def test_failure_in_one_account_does_not_affect_others(env, tmp_path, fake_claude, monkeypatch):
    a, b = make_profile(tmp_path, "claude", "a"), make_profile(tmp_path, "claude", "b")
    configure(env, tmp_path, {"claude": [a, b]})
    real_run = subprocess.run

    def run(cmd, env=None, **kw):
        if env["CLAUDE_CONFIG_DIR"] == a["claude_dir"]:
            raise subprocess.TimeoutExpired(cmd, 1)
        return real_run(cmd, env=env, **kw)

    monkeypatch.setattr(renew.subprocess, "run", run)
    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    assert fake_claude.calls() == [f"{b['claude_dir']}|auth status"]
    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["claude:a"]["error"] == "timeout"
    assert state["renewals"]["claude:b"]["error"] is None
    assert len(status["agents"]["claude"]["accounts"]) == 2


def test_nonzero_exit_is_failed_and_no_secret_leaks(env, tmp_path, fake_claude):
    prof = make_profile(tmp_path, "claude", "a", token="SEGREDO-123")
    configure(env, tmp_path, {"claude": [prof]})
    fake_claude.install(fail=True)

    env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    state_file = env["cache"].parent / "refresh_state.json"
    assert json.loads(state_file.read_text())["renewals"]["claude:a"]["error"] == "failed"
    assert "SEGREDO-123" not in state_file.read_text() + env["cache"].read_text()
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600


def test_codex_and_gemini_are_not_renewed_yet(env, tmp_path, fake_claude):
    configure(env, tmp_path, {"codex": [make_profile(tmp_path, "codex", "c")], "gemini": [make_profile(tmp_path, "gemini", "g")]})
    env["run"](http=FakeHttp(codex=[API_OK["codex"]], gemini=[API_OK["gemini"]], claude=[API_OK["claude"]]))
    assert fake_claude.calls() == []
