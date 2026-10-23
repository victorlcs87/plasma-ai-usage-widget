"""Salvaguardas da renovacao de Conta inativa (revisao da Spec 08): fail-closed da Conta Ativa, so quando
precisa, "Atualizar agora", orcamento, confinamento ao Perfil Isolado, ambiente do filho e limites de leitura.

Tudo com falsos e diretorios temporarios; nenhuma CLI real e executada.
"""

import base64
import json
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from ai_usage_collector import renew
from test_refresh import API_OK, T0, FakeHttp, FakeResp, configure, env, make_expired_profile, make_profile  # noqa: F401
from test_renew import REAL_RENEWERS, install_system

STATE = lambda env: json.loads((env["cache"].parent / "refresh_state.json").read_text())  # noqa: E731


@pytest.fixture
def calls(monkeypatch):
    """Renovador falso de Claude: registra o perfil e nao faz nada."""
    seen = []
    monkeypatch.setattr(renew, "RENEWERS", {"claude": seen.append})
    return seen


def run(env, http=None):
    return env["run"]("--provider", "claude", http=http or FakeHttp(claude=[API_OK["claude"]]))


def system_with_refresh(tmp_path, refresh, ident=None, access="tok-sys"):
    sys_dir = tmp_path / "_sys_claude"
    sys_dir.mkdir(exist_ok=True)
    (sys_dir / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": access, "refreshToken": refresh}}))
    if ident:
        (sys_dir / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": ident}}))


def profile_with_refresh(tmp_path, name, refresh, ident=None):
    prof = make_expired_profile(tmp_path, "claude", name, token=f"tok-{name}", ident=ident)
    data = json.loads(Path(prof["credential_path"]).read_text())
    data["claudeAiOauth"]["refreshToken"] = refresh
    Path(prof["credential_path"]).write_text(json.dumps(data))
    return prof


# --- 1. Conta Ativa: fail-closed -------------------------------------------------------------

def test_profile_sharing_refresh_token_with_system_is_never_renewed(env, tmp_path, calls):
    prof = profile_with_refresh(tmp_path, "dup", "RT-COMPARTILHADO", ident="uuid-b")  # identidade diferente
    system_with_refresh(tmp_path, "RT-COMPARTILHADO", ident="uuid-a")
    configure(env, tmp_path, {"claude": [prof]})

    run(env)

    assert calls == []
    assert "claude:dup" not in STATE(env)["renewals"]  # pulada nao e tentativa


def test_failing_detection_skips_instead_of_renewing(env, tmp_path, calls, monkeypatch, capsys):
    configure(env, tmp_path, {"claude": [make_expired_profile(tmp_path, "claude", "a", ident="uuid-a")]})

    def boom(*_a, **_k):
        raise OSError("leitura falhou")

    monkeypatch.setattr(renew, "get_active_credentials", boom)
    monkeypatch.setattr("ai_usage_collector.collector.detect_active_account_id", boom)

    run(env)

    assert calls == []
    assert "detection_failed" in capsys.readouterr().err


def test_unreadable_system_credential_file_skips(env, tmp_path, calls):
    configure(env, tmp_path, {"claude": [make_expired_profile(tmp_path, "claude", "a", ident="uuid-a")]})
    sys_dir = tmp_path / "_sys_claude"
    sys_dir.mkdir()
    (sys_dir / ".credentials.json").write_text("{ nao e json")  # existe, mas get_active_credentials devolve None

    run(env)

    assert calls == []


def test_unknown_identity_on_either_side_skips(env, tmp_path, calls):
    system_with_refresh(tmp_path, "RT-SIS", ident="uuid-a")
    configure(env, tmp_path, {"claude": [make_expired_profile(tmp_path, "claude", "semid")]})  # perfil sem identidade
    run(env)
    assert calls == []


def test_unknown_system_identity_skips(env, tmp_path, calls):
    system_with_refresh(tmp_path, "RT-SIS", ident=None)
    configure(env, tmp_path, {"claude": [make_expired_profile(tmp_path, "claude", "a", ident="uuid-b")]})
    run(env)
    assert calls == []


def test_same_identity_with_different_tokens_skips(env, tmp_path, calls):
    system_with_refresh(tmp_path, "RT-SIS", ident="uuid-a")
    configure(env, tmp_path, {"claude": [profile_with_refresh(tmp_path, "mesma", "RT-OUTRO", ident="uuid-a")]})
    run(env)
    assert calls == []


def test_known_distinct_identity_is_renewed(env, tmp_path, calls):
    system_with_refresh(tmp_path, "RT-SIS", ident="uuid-a")
    configure(env, tmp_path, {"claude": [profile_with_refresh(tmp_path, "outra", "RT-OUTRO", ident="uuid-b")]})
    run(env)
    assert len(calls) == 1


# --- 2. So quando precisa --------------------------------------------------------------------

def _jwt(exp):
    seg = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{seg({'alg': 'none'})}.{seg({'exp': exp})}.sig"


def _write(path, data):
    path.write_text(json.dumps(data))
    return path


NOW = T0.timestamp()


def test_needs_renewal_claude_uses_expires_at_ms_and_iso(tmp_path):
    f = tmp_path / "c.json"
    far = int((NOW + 8 * 3600) * 1000)
    assert not renew.needs_renewal("claude", _write(f, {"claudeAiOauth": {"expiresAt": far}}), NOW, 3600)
    soon = int((NOW + 3600 + 200) * 1000)  # vence dentro de intervalo + margem
    assert renew.needs_renewal("claude", _write(f, {"claudeAiOauth": {"expiresAt": soon}}), NOW, 3600)
    past = (T0 - timedelta(hours=1)).isoformat()
    assert renew.needs_renewal("claude", _write(f, {"claudeAiOauth": {"expiresAt": past}}), NOW, 3600)


def test_needs_renewal_codex_reads_jwt_exp_only(tmp_path):
    f = tmp_path / "a.json"
    assert not renew.needs_renewal("codex", _write(f, {"tokens": {"access_token": _jwt(NOW + 86400)}}), NOW, 3600)
    assert renew.needs_renewal("codex", _write(f, {"tokens": {"access_token": _jwt(NOW + 60)}}), NOW, 3600)


def test_needs_renewal_gemini_expiry_forms(tmp_path):
    f = tmp_path / "g.json"
    assert not renew.needs_renewal("gemini", _write(f, {"expiry_date": int((NOW + 86400) * 1000)}), NOW, 3600)
    assert renew.needs_renewal("gemini", _write(f, {"expiry": (T0 + timedelta(minutes=10)).isoformat()}), NOW, 3600)
    long_ttl = _write(f, {"expires_in": 99999})  # relativo ao mtime do arquivo
    assert not renew.needs_renewal("gemini", long_ttl, time.time(), 3600)


@pytest.mark.parametrize("creds", [{}, {"claudeAiOauth": {}}, {"claudeAiOauth": {"expiresAt": "lixo"}}])
def test_unknown_expiry_renews(tmp_path, creds):
    assert renew.needs_renewal("claude", _write(tmp_path / "c.json", creds), NOW, 3600)
    assert renew.needs_renewal("claude", tmp_path / "nao-existe.json", NOW, 3600)


def test_valid_token_is_not_renewed_and_keeps_refresh_token_untouched(env, tmp_path, calls):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})  # vale 5 dias
    run(env)
    assert calls == []
    assert "claude:a" not in STATE(env)["renewals"]


def test_token_expiring_before_next_interval_is_renewed(env, tmp_path, calls):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a", expired=timedelta(minutes=30))]})
    run(env)
    assert len(calls) == 1


# --- 3. "Atualizar agora" ---------------------------------------------------------------------

def test_force_renew_bypasses_the_interval_throttle_but_scheduler_does_not(env, tmp_path, monkeypatch):
    n = []

    def failing(_profile):
        n.append(1)
        raise renew.RenewError("network")  # falha transitoria

    monkeypatch.setattr(renew, "RENEWERS", {"claude": failing})
    configure(env, tmp_path, {"claude": [make_expired_profile(tmp_path, "claude", "a")]})
    run(env)
    env["clock"]["now"] = T0 + timedelta(minutes=10)
    run(env)  # agendador: dentro do Intervalo, nao tenta de novo
    assert len(n) == 1

    env["run"]("--provider", "claude", "--force-renew", http=FakeHttp(claude=[API_OK["claude"]]))  # "Atualizar agora"
    assert len(n) == 2


def test_force_renew_still_honors_active_account_and_token_validity(env, tmp_path, calls):
    system_with_refresh(tmp_path, "RT", ident="uuid-a")
    ativa = profile_with_refresh(tmp_path, "ativa", "RT", ident="uuid-a")
    valida = make_profile(tmp_path, "claude", "valida", ident="uuid-v")
    configure(env, tmp_path, {"claude": [ativa, valida]})

    env["run"]("--provider", "claude", "--force-renew", http=FakeHttp(claude=[API_OK["claude"]]))

    assert calls == []


def test_plasmoid_sends_force_renew_only_from_refresh_now():
    main = (Path(__file__).parent.parent / "plasmoid/contents/ui/main.qml").read_text()
    assert 'Collector.shellQuote("--force-renew")' in main
    assert "runCollectorRefresh(null, true)" in main  # Atualizar agora
    assert "runCollectorRefresh(due)" in main  # agendador de 15 s: sem a flag


# --- 4. Orcamento por ciclo -------------------------------------------------------------------

def test_budget_defers_remaining_accounts_without_marking_failure(env, tmp_path, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(renew, "_clock", lambda: clock["t"])
    done = []

    def slow(profile):
        done.append(Path(profile).name)
        clock["t"] += 30  # estoura o orcamento restante

    monkeypatch.setattr(renew, "RENEWERS", {"claude": slow})
    accs = [make_expired_profile(tmp_path, "claude", n) for n in ("a", "b", "c")]
    configure(env, tmp_path, {"claude": accs})

    status = run(env)

    assert done == ["a"]
    assert set(STATE(env)["renewals"]) == {"claude:a"}  # as adiadas nao viram falha nem consomem o Intervalo
    assert all("renewal" not in a for a in status["agents"]["claude"]["accounts"][1:])

    run(env)  # proximo ciclo: orcamento novo, renova a seguinte
    assert done == ["a", "b"]


# --- 5. Confinamento ---------------------------------------------------------------------------

def test_profile_outside_profiles_root_is_not_renewed(env, tmp_path, calls):
    prof = make_expired_profile(tmp_path, "claude", "a")
    outside = tmp_path / "fora"
    outside.mkdir()
    (outside / ".credentials.json").write_text(Path(prof["credential_path"]).read_text())
    prof.update(claude_dir=str(outside), credential_path=str(outside / ".credentials.json"))
    configure(env, tmp_path, {"claude": [prof]})
    run(env)
    assert calls == []


def test_fixed_system_dir_profile_is_not_renewed(env, tmp_path, calls):
    home_claude = tmp_path / "_home" / ".claude"  # HOME isolado pelo conftest
    home_claude.mkdir()
    cred = home_claude / ".credentials.json"
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "t", "expiresAt": 1}}))
    configure(env, tmp_path, {"claude": [{"id": "x", "label": "x", "claude_dir": str(home_claude), "credential_path": str(cred)}]})
    run(env)
    assert calls == []


def test_symlinked_credential_file_is_not_renewed(env, tmp_path, calls):
    prof = make_expired_profile(tmp_path, "claude", "a")
    real = tmp_path / "alvo.json"
    real.write_text(Path(prof["credential_path"]).read_text())
    Path(prof["credential_path"]).unlink()
    Path(prof["credential_path"]).symlink_to(real)
    configure(env, tmp_path, {"claude": [prof]})
    run(env)
    assert calls == []


# --- 6. Ambiente do subprocesso ----------------------------------------------------------------

SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "GITHUB_TOKEN")


def _install_env_dumper(tmp_path, name):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    out = tmp_path / f"{name}_env.txt"
    exe = bin_dir / name
    exe.write_text(f'#!/bin/sh\nenv > "{out}"\ncat > /dev/null &\necho \'{{"id":2,"result":{{}}}}\'\nexit 0\n')
    exe.chmod(0o755)
    return bin_dir, out


@pytest.mark.parametrize("name,var", [("claude", "CLAUDE_CONFIG_DIR"), ("codex", "CODEX_HOME")])
def test_child_does_not_inherit_secret_environment(tmp_path, monkeypatch, name, var):
    bin_dir, out = _install_env_dumper(tmp_path, name)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for k in SECRETS:
        monkeypatch.setenv(k, "SEGREDO-NAO-VAZAR")
    profile = tmp_path / "perfil"
    profile.mkdir()

    REAL_RENEWERS[name](profile)

    dumped = out.read_text()
    assert "SEGREDO-NAO-VAZAR" not in dumped
    assert f"{var}={profile}" in dumped
    assert "LC_ALL=C.UTF-8" in dumped and "XDG_CONFIG_HOME=" in dumped and "PATH=" in dumped


# --- 8. Limites e higiene -----------------------------------------------------------------------

def test_codex_unbounded_output_without_newline_is_failed(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "codex"
    exe.write_text("#!/bin/sh\nhead -c 3000000 /dev/zero | tr '\\0' 'x'\nsleep 5\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    with pytest.raises(renew.RenewError) as exc:
        renew._codex_refresh(tmp_path)
    assert exc.value.code == "failed"


def test_timeout_kills_the_whole_process_group(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pidfile = tmp_path / "neto.pid"
    exe = bin_dir / "claude"
    exe.write_text(f'#!/bin/sh\nsleep 60 &\necho $! > "{pidfile}"\nwait\n')
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(renew, "TIMEOUT_SECONDS", 1)

    with pytest.raises(renew.subprocess.TimeoutExpired):
        REAL_RENEWERS["claude"](tmp_path)

    pid = int(pidfile.read_text())
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    os.kill(pid, 9)
    pytest.fail("o processo neto sobreviveu ao timeout")


def test_oversized_agy_binary_is_rejected(tmp_path, monkeypatch):
    agy = tmp_path / "agy"
    agy.write_bytes(b"x" * 100)
    monkeypatch.setattr(renew.shutil, "which", lambda _n: str(agy))
    monkeypatch.setattr(renew, "MAX_BINARY_BYTES", 10)
    with pytest.raises(renew.RenewError) as exc:
        renew._agy_binary()
    assert exc.value.code == "binary_unreadable"


def test_refresh_response_read_is_bounded(monkeypatch):
    seen = []

    class Resp(FakeResp):
        def read(self, amt=-1):
            seen.append(amt)
            return super().read()

    class Opener:
        def open(self, req, timeout=None):
            return Resp({"access_token": "t", "expires_in": 10})

    monkeypatch.setattr(renew.refresh, "NO_REDIRECT_OPENER", Opener())
    renew._post_refresh("cid", "sec", "rt")
    assert seen == [renew.MAX_READ_BYTES]


def test_atomic_write_fsyncs_file_and_dir_and_cleans_old_temp_files(tmp_path, monkeypatch):
    old = tmp_path / ".oauth_velho.tmp"
    old.write_text("x")
    os.utime(old, (1, 1))
    fresh = tmp_path / ".oauth_novo.tmp"  # de outra gravacao em andamento: fica
    fresh.write_text("x")
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    renew._write_private_atomic(tmp_path / "oauth_creds.json", {"a": 1})

    assert len(synced) == 2
    assert not old.exists() and fresh.exists()
    assert oct((tmp_path / "oauth_creds.json").stat().st_mode & 0o777) == "0o600"


def test_account_id_is_repr_sanitized_on_stderr(env, tmp_path, monkeypatch, capsys):
    def failing(_p):
        raise renew.RenewError("failed")

    monkeypatch.setattr(renew, "RENEWERS", {"claude": failing})
    prof = make_expired_profile(tmp_path, "claude", "a")
    prof["id"] = "a\nAviso: forjado"
    configure(env, tmp_path, {"claude": [prof]})
    run(env)
    err = capsys.readouterr().err
    assert "\nAviso: forjado" not in err
    assert "'claude:a\\nAviso: forjado'" in err
