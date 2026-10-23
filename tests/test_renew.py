"""Renovacao de Conta inativa pela CLI (Spec 08, ticket 57): Claude, `claude auth status` no Perfil Isolado."""

import json
import stat
import subprocess
from pathlib import Path
from datetime import timedelta

import pytest

from ai_usage_collector import renew
REAL_RENEWERS = dict(renew.RENEWERS)
from test_refresh import API_OK, T0, FakeHttp, acc_of, configure, env, make_expired_profile, make_profile  # noqa: F401

FAKE_CLAUDE = """#!/bin/sh
echo "$CLAUDE_CONFIG_DIR|$*" >> "{log}"
[ -n "{fail}" ] && exit 1
cat > "$CLAUDE_CONFIG_DIR/.credentials.json" <<EOF
{{"claudeAiOauth": {{"accessToken": "tok-renovado", "expiresAt": "{future}"}}}}
EOF
"""


def install_system(tmp_path, provider, profile, ident=None):
    """Credencial de sistema (conftest aponta CLAUDE_CONFIG_DIR/CODEX_HOME para _sys_*) copiada de um perfil."""
    sys_dir = tmp_path / f"_sys_{provider}"
    sys_dir.mkdir(exist_ok=True)
    name = Path(profile["credential_path"]).name
    (sys_dir / name).write_text(open(profile["credential_path"]).read())
    if ident:
        (sys_dir / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": ident}}))
    return sys_dir


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
    prof = make_expired_profile(tmp_path, "claude", "cga")
    expire(prof)
    configure(env, tmp_path, {"claude": [prof]})
    http = FakeHttp(claude=[API_OK["claude"]])

    status = env["run"]("--provider", "claude", http=http)

    assert fake_claude.calls() == [f"{prof['claude_dir']}|auth status"]
    acc = acc_of(status, "claude")
    assert acc["native_window"]["usage_percentage"] == 42.0
    assert "fetch_error" not in acc


def test_active_system_account_is_never_renewed(env, tmp_path, fake_claude):
    active = make_expired_profile(tmp_path, "claude", "ativa", token="tok-ativa", ident="uuid-a")
    other = make_expired_profile(tmp_path, "claude", "outra", token="tok-outra", ident="uuid-b")
    install_system(tmp_path, "claude", active, ident="uuid-a")
    configure(env, tmp_path, {"claude": [active, other]})

    env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    assert fake_claude.calls() == [f"{other['claude_dir']}|auth status"]


def test_at_most_one_renewal_per_account_per_interval(env, tmp_path, fake_claude):
    prof = make_expired_profile(tmp_path, "claude", "a")
    configure(env, tmp_path, {"claude": [prof]})
    http = FakeHttp(claude=[API_OK["claude"]])
    env["run"]("--provider", "claude", http=http)
    expire(prof)  # o falso renovou por 8 h; vence de novo para provar o limite por Intervalo
    env["clock"]["now"] = T0 + timedelta(minutes=30)
    env["run"](http=http)  # dentro do intervalo
    assert len(fake_claude.calls()) == 1

    env["clock"]["now"] = T0 + timedelta(hours=1, seconds=1)
    env["run"](http=http)
    assert len(fake_claude.calls()) == 2


def test_missing_cli_does_not_break_cycle_and_is_classified(env, tmp_path, fake_claude, capsys):
    (fake_claude.dir / "claude").unlink()
    a, b = make_expired_profile(tmp_path, "claude", "a"), make_expired_profile(tmp_path, "claude", "b")
    configure(env, tmp_path, {"claude": [a, b]})

    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    assert [x["native_window"]["usage_percentage"] for x in status["agents"]["claude"]["accounts"]] == [42.0, 42.0]
    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["claude:a"]["error"] == "cli_missing"
    assert "cli_missing" in capsys.readouterr().err


def test_failure_in_one_account_does_not_affect_others(env, tmp_path, fake_claude, monkeypatch):
    a, b = make_expired_profile(tmp_path, "claude", "a"), make_expired_profile(tmp_path, "claude", "b")
    configure(env, tmp_path, {"claude": [a, b]})
    real_popen = subprocess.Popen

    def popen(cmd, env=None, **kw):
        if env["CLAUDE_CONFIG_DIR"] == a["claude_dir"]:
            raise subprocess.TimeoutExpired(cmd, 1)
        return real_popen(cmd, env=env, **kw)

    monkeypatch.setattr(renew.subprocess, "Popen", popen)
    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    assert fake_claude.calls() == [f"{b['claude_dir']}|auth status"]
    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["claude:a"]["error"] == "timeout"
    assert state["renewals"]["claude:b"]["error"] is None
    assert len(status["agents"]["claude"]["accounts"]) == 2


def test_nonzero_exit_is_failed_and_no_secret_leaks(env, tmp_path, fake_claude):
    prof = make_expired_profile(tmp_path, "claude", "a", token="SEGREDO-123")
    configure(env, tmp_path, {"claude": [prof]})
    fake_claude.install(fail=True)

    env["run"]("--provider", "claude", http=FakeHttp(claude=[API_OK["claude"]]))

    state_file = env["cache"].parent / "refresh_state.json"
    assert json.loads(state_file.read_text())["renewals"]["claude:a"]["error"] == "failed"
    assert "SEGREDO-123" not in state_file.read_text() + env["cache"].read_text()
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600


FAKE_CODEX = """#!/bin/sh
echo "$CODEX_HOME|$*" >> "{log}"
while read line; do
  case "$line" in
    *account/read*) [ -n "{write}" ] && echo "$line" > "$CODEX_HOME/renovado"; {reply};;
  esac
done
"""
OK_REPLY = """echo '{"id":2,"result":{"requiresOpenaiAuth":true}}'"""


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "codex_calls.log"

    def install(reply=OK_REPLY, write=True):
        exe = bin_dir / "codex"
        exe.write_text(FAKE_CODEX.format(log=log, reply=reply, write="1" if write else ""))
        exe.chmod(0o755)

    install()
    monkeypatch.setattr(renew, "RENEWERS", REAL_RENEWERS)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    calls = lambda: log.read_text().splitlines() if log.exists() else []  # noqa: E731
    return type("F", (), {"install": staticmethod(install), "calls": staticmethod(calls)})


def test_codex_inactive_profile_is_renewed_via_app_server_once_per_interval(env, tmp_path, fake_codex):
    prof = make_expired_profile(tmp_path, "codex", "c")
    configure(env, tmp_path, {"codex": [prof]})
    http = FakeHttp(codex=[API_OK["codex"]])

    env["run"]("--provider", "codex", http=http)
    env["clock"]["now"] = T0 + timedelta(minutes=30)
    env["run"](http=http)

    assert fake_codex.calls() == [f"{prof['codex_dir']}|app-server --listen stdio://"]
    assert "refreshToken" in (Path(prof["codex_dir"]) / "renovado").read_text()


def test_codex_active_account_is_never_renewed(env, tmp_path, fake_codex):
    active = make_expired_profile(tmp_path, "codex", "ativa", ident="acc-a")
    install_system(tmp_path, "codex", active)
    configure(env, tmp_path, {"codex": [active]})

    env["run"]("--provider", "codex", http=FakeHttp(codex=[API_OK["codex"]]))

    assert fake_codex.calls() == []


def test_codex_rpc_error_is_failed_and_cycle_continues(env, tmp_path, fake_codex):
    prof = make_expired_profile(tmp_path, "codex", "c", token="SEGREDO-123")
    configure(env, tmp_path, {"codex": [prof]})
    fake_codex.install(reply="""echo '{"id":2,"error":{"message":"SEGREDO-123"}}'""", write=False)

    status = env["run"]("--provider", "codex", http=FakeHttp(codex=[API_OK["codex"]]))

    state_file = env["cache"].parent / "refresh_state.json"
    assert json.loads(state_file.read_text())["renewals"]["codex:c"]["error"] == "failed"
    assert "SEGREDO-123" not in state_file.read_text() + env["cache"].read_text()
    assert len(status["agents"]["codex"]["accounts"]) == 1


def test_codex_missing_cli_is_classified(env, tmp_path, monkeypatch):
    monkeypatch.setattr(renew, "RENEWERS", REAL_RENEWERS)
    monkeypatch.setenv("PATH", str(tmp_path))  # /usr/bin tem o codex real
    configure(env, tmp_path, {"codex": [make_expired_profile(tmp_path, "codex", "c")]})
    env["run"]("--provider", "codex", http=FakeHttp(codex=[API_OK["codex"]]))
    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["codex:c"]["error"] == "cli_missing"


def test_codex_replies_arriving_together_with_noise_are_not_a_timeout(env, tmp_path, fake_codex, monkeypatch):
    monkeypatch.setattr(renew, "TIMEOUT_SECONDS", 3)
    configure(env, tmp_path, {"codex": [make_expired_profile(tmp_path, "codex", "c")]})
    fake_codex.install(reply="""printf 'lixo\\n{"id":1,"result":{}}\\n{"id":2,"result":{}}\\n'""")

    env["run"]("--provider", "codex", http=FakeHttp(codex=[API_OK["codex"]]))

    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["codex:c"]["error"] is None


def test_codex_exit_before_reply_is_failed(env, tmp_path, fake_codex):
    configure(env, tmp_path, {"codex": [make_expired_profile(tmp_path, "codex", "c")]})
    fake_codex.install(reply="exit 0", write=False)

    env["run"]("--provider", "codex", http=FakeHttp(codex=[API_OK["codex"]]))

    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["codex:c"]["error"] == "failed"


def test_codex_hang_times_out(env, tmp_path, fake_codex, monkeypatch):
    monkeypatch.setattr(renew, "TIMEOUT_SECONDS", 1)
    configure(env, tmp_path, {"codex": [make_expired_profile(tmp_path, "codex", "c")]})
    fake_codex.install(reply="true", write=False)  # nunca responde

    env["run"]("--provider", "codex", http=FakeHttp(codex=[API_OK["codex"]]))

    state = json.loads((env["cache"].parent / "refresh_state.json").read_text())
    assert state["renewals"]["codex:c"]["error"] == "timeout"


