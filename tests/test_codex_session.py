"""Ticket 36: Estado da Sessao do Codex (notify opt-in + mtime dos rollouts), pela CLI, com HOME e CODEX_HOME falsos."""
import json
import os
import subprocess
import sys
import tomllib

import pytest

from ai_usage_collector import codex_hooks, session_state
from ai_usage_collector.cli import main

USER_TOML = '# meu config\nmodel = "gpt-5"\n\n[projects."/x"]\ntrust_level = "trusted"  # ok\n'


@pytest.fixture
def env(tmp_path):
    chome = tmp_path / "_sys_codex"  # conftest ja aponta CODEX_HOME para ca
    chome.mkdir()
    return chome, tmp_path / "cache" / "status.json", chome / "config.toml"


def run(cache, *args):
    return main(["--cache-path", str(cache), *args])


def rollout(chome, mtime, day="2026/10/20", name="rollout-a.jsonl"):
    d = chome / "sessions" / day
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text('{"payload": {"text": "SEGREDO"}}\n')
    os.utime(f, (mtime, mtime))
    return f


def test_nothing_installed_without_command(env):
    chome, cache, cfg = env
    run(cache, "--session-state")
    assert not cfg.exists()
    run(cache, "--install-hooks")  # sem argumento: so o Claude
    assert not cfg.exists()


def test_install_idempotent_uninstall_preserves_user_toml(env, capsys):
    chome, cache, cfg = env
    cfg.write_text(USER_TOML)
    cfg.chmod(0o640)
    assert run(cache, "--install-hooks", "codex") == 0
    first = cfg.read_text()
    assert first.endswith(USER_TOML) and first.startswith("notify = [") and first.splitlines()[0].endswith(codex_hooks.MARKER)
    data = tomllib.loads(first)
    assert data["notify"][1:3] == ["-I", str(session_state.Path(session_state.__file__).resolve())]
    assert data["notify"][-1] == str(chome.resolve()) and tomllib.loads(USER_TOML).items() <= data.items()
    assert cfg.stat().st_mode & 0o777 == 0o640
    bak = cfg.with_name("config.toml.plasma-ai-usage.bak")
    assert bak.read_text() == USER_TOML and bak.stat().st_mode & 0o777 == 0o600
    assert run(cache, "--install-hooks", "codex") == 0 and cfg.read_text() == first
    assert "já estava" in capsys.readouterr().out
    assert run(cache, "--uninstall-hooks", "codex") == 0 and cfg.read_text() == USER_TOML
    assert run(cache, "--uninstall-hooks", "codex") == 0


def test_existing_user_notify_never_overwritten(env, capsys):
    chome, cache, cfg = env
    for content in ('notify = ["say", "oi"]\n' + USER_TOML, 'notify = ["a"]  # meu\n', "notify.x = 1\n"):
        cfg.write_text(content)
        assert run(cache, "--install-hooks", "codex") == 1
        assert cfg.read_text() == content and "notify" in capsys.readouterr().err
        assert run(cache, "--uninstall-hooks", "codex") == 0 and cfg.read_text() == content


def test_notify_inside_table_is_not_a_root_notify(env):
    chome, cache, cfg = env
    cfg.write_text('[tui]\nnotify = ["x"]\n')  # chave de outra tabela: nao conflita
    assert run(cache, "--install-hooks", "codex") == 0
    assert tomllib.loads(cfg.read_text())["tui"] == {"notify": ["x"]} and "notify" in tomllib.loads(cfg.read_text())
    assert run(cache, "--uninstall-hooks", "codex") == 0 and cfg.read_text() == '[tui]\nnotify = ["x"]\n'


def test_marker_inside_multiline_string_aborts_untouched(env):
    chome, cache, cfg = env
    content = 'texto = """\nnotify = ["x"] ' + codex_hooks.MARKER + '\n"""\n'
    cfg.write_text(content)
    assert run(cache, "--uninstall-hooks", "codex") == 1 and cfg.read_text() == content
    assert run(cache, "--install-hooks", "codex") == 1 and cfg.read_text() == content


def test_missing_and_empty_config(env):
    chome, cache, cfg = env
    assert run(cache, "--uninstall-hooks", "codex") == 0 and not cfg.exists()
    assert run(cache, "--install-hooks", "codex") == 0
    assert cfg.stat().st_mode & 0o777 == 0o600 and not cfg.with_name("config.toml.plasma-ai-usage.bak").exists()
    assert run(cache, "--uninstall-hooks", "codex") == 0 and cfg.read_text() == ""
    cfg.write_text("  \n")
    assert run(cache, "--install-hooks", "codex") == 0 and cfg.read_text().endswith("  \n")


@pytest.mark.parametrize("content", ["model = ", "[a\nb=1", "a = 1\na = 2\n"])
def test_invalid_toml_aborts_untouched(env, content, capsys):
    chome, cache, cfg = env
    cfg.write_text(content)
    assert run(cache, "--install-hooks", "codex") == 1
    assert cfg.read_text() == content and "TOML" in capsys.readouterr().err
    assert cfg.with_name("config.toml.plasma-ai-usage.bak").read_text() == content


def test_symlink_preserved(env, tmp_path):
    chome, cache, cfg = env
    real = tmp_path / "dotfiles" / "config.toml"
    real.parent.mkdir()
    real.write_text(USER_TOML)
    cfg.symlink_to(real)
    assert run(cache, "--install-hooks", "codex") == 0
    assert cfg.is_symlink() and "notify" in tomllib.loads(real.read_text())
    assert run(cache, "--uninstall-hooks", "codex") == 0 and cfg.is_symlink() and real.read_text() == USER_TOML


def test_relative_codex_home_refused(env, monkeypatch, capsys):
    chome, cache, cfg = env
    monkeypatch.setenv("CODEX_HOME", "relativo")
    assert run(cache, "--install-hooks", "codex") == 1 and "absoluto" in capsys.readouterr().err


def test_all_installs_both_and_provider_validated(env, capsys):
    chome, cache, cfg = env
    assert run(cache, "--install-hooks", "all") == 0
    assert "hooks" in json.loads((chome.parent / "_sys_claude" / "settings.json").read_text()) and "notify" in tomllib.loads(cfg.read_text())
    assert run(cache, "--uninstall-hooks", "all") == 0 and cfg.read_text() == ""
    with pytest.raises(SystemExit):
        run(cache, "--install-hooks", "gemini")


def test_all_reports_codex_error_but_still_does_claude(env):
    chome, cache, cfg = env
    cfg.write_text("model = ")
    assert run(cache, "--install-hooks", "all") == 1
    assert (chome.parent / "_sys_claude" / "settings.json").exists()


def notify(tmp_path, chome, payload, *, via_command=True):
    """Executa o comando REGISTRADO no config.toml (sem shell, como o Codex), com o JSON como ultimo argumento."""
    run(tmp_path / "cache" / "status.json", "--install-hooks", "codex")
    argv = tomllib.loads((chome / "config.toml").read_text())["notify"]
    return subprocess.run([*argv, payload], capture_output=True, text=True, stdin=subprocess.DEVNULL)


def test_registered_notify_runs_safely_and_records_idle(env, tmp_path):
    chome, cache, cfg = env
    payload = json.dumps({"type": "agent-turn-complete", "thread-id": "t-1", "turn-id": "1", "cwd": "/x",
                          "input-messages": ["SEGREDO-do-prompt"], "last-assistant-message": "SEGREDO-resposta"})
    r = notify(tmp_path, chome, payload)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    sdir = cache.parent / "session-state"
    files = list(sdir.glob("*.json"))
    assert len(files) == 1 and "t-1" not in files[0].name and files[0].stat().st_mode & 0o777 == 0o600
    raw = files[0].read_text()
    assert "SEGREDO" not in raw and "t-1" not in raw
    rec = json.loads(raw)
    assert rec["state"] == "idle" and rec["config_dir"] == str(chome.resolve())


@pytest.mark.parametrize("payload", [
    "", "{broken", "[1]", json.dumps({"type": "outro", "thread-id": "t"}), json.dumps({"type": "agent-turn-complete"}),
    json.dumps({"type": "agent-turn-complete", "thread-id": "../../x y"}), json.dumps({"type": "agent-turn-complete", "thread-id": 5}),
    json.dumps({"input-messages": ['"type": "agent-turn-complete", "thread-id": "forjado"']}),
    "x" * 100_000, json.dumps({"type": "agent-turn-complete", "thread-id": "t", "pad": "y" * 100_000}),
])
def test_hostile_notify_argument_records_nothing_and_exits_0(env, tmp_path, payload):
    chome, cache, cfg = env
    r = notify(tmp_path, chome, payload)
    assert r.returncode == 0 and not r.stdout
    recorded = list((cache.parent / "session-state").glob("*.json"))
    assert len(recorded) == (1 if '"pad"' in payload else 0)  # JSON valido e grande: o evento vale; o resto e ignorado


def test_notify_with_missing_args_exits_0():
    r = subprocess.run([sys.executable, "-I", session_state.__file__, "--codex-notify"], capture_output=True)
    assert r.returncode == 0 and r.stdout == b""


def states(chome, now, idle_at=None, sdir=None):
    sdir = sdir or chome.parent / "sdir"
    if idle_at is not None:
        session_state.write_event(sdir, "idle", "t", idle_at, config_dir=str(chome))
    return session_state.states_from_dirs({"a": [str(chome)]}, sdir, now, "codex")["a"]


def test_state_from_rollout_mtime_and_ttl(env):
    chome, _, _ = env
    now = 1_000_000.0
    assert states(chome, now) == "unknown"  # sem sessoes, sem estado
    rollout(chome, now - 5)
    assert states(chome, now) == "busy"
    assert states(chome, now + session_state.CODEX_BUSY_SECONDS + 5) == "idle"  # parou de escrever
    assert states(chome, now + session_state.TTL_SECONDS["idle"] + 5) == "unknown"


def test_notify_ends_busy_immediately_but_new_writes_reopen(env):
    chome, _, _ = env
    now = 1_000_000.0
    f = rollout(chome, now - 1)
    assert states(chome, now, idle_at=now) == "idle"  # turno acabou; escrita de fechamento nao reabre
    os.utime(f, (now + 10, now + 10))  # novo turno escreveu depois do notify
    assert states(chome, now + 11) == "busy"


def test_rollouts_other_days_and_other_dirs_ignored(env):
    chome, _, _ = env
    now = 1_000_000.0
    for d in ("2026/10/01", "2026/10/02", "2026/10/03"):
        rollout(chome, now - 1 if d == "2026/10/01" else now - 99999, day=d)  # so o antigo e recente, mas fora dos 2 dias mais novos
    assert states(chome, now) == "unknown"
    other = chome.parent / "outro"
    rollout(other, now - 1)
    assert states(chome, now) == "unknown"  # outro CODEX_HOME nao conta para esta Conta


def test_missing_dirs_and_garbage_tolerated(tmp_path):
    assert session_state.states_from_dirs({"a": [str(tmp_path / "nada")], "b": []}, tmp_path / "nada", 1.0, "codex") == {"a": "unknown", "b": "unknown"}
    (tmp_path / "x" / "sessions" / "2026" / "10" / "20" / "rollout-d.jsonl").mkdir(parents=True)  # diretorio, nao arquivo
    assert session_state.codex_busy_mtime(tmp_path / "x") is not None


def codex_cfg(env, chome_acc_dir=None):
    chome, cache, _ = env
    cfg = cache.parent / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    (chome / "auth.json").write_text(json.dumps({"tokens": {"access_token": "t", "refresh_token": "r"}}))
    cfg.write_text(json.dumps({"agents": {"codex": {"accounts": [{"id": "c1", "label": "C", "credential_path": str(chome / "auth.json")}]}}}))
    return cfg


def test_contract_and_light_path_expose_codex_state(env):
    from ai_usage_collector.contract import validate_status_contract

    chome, cache, _ = env
    cfg = codex_cfg(env)
    assert run(cache, "--config-path", str(cfg), "--status") == 0
    rollout(chome, __import__("time").time() - 1)
    assert run(cache, "--config-path", str(cfg), "--refresh") == 0
    status = json.loads(cache.read_text())
    assert validate_status_contract(status)
    accs = status["agents"]["codex"]["accounts"]
    assert [a.get("session_state") for a in accs] == ["busy"]
    out = subprocess.run([sys.executable, "-I", "-c", "import ai_usage_collector.session_state as m, sys; m.states_main([sys.argv[1]]); "
                          "assert 'ai_usage_collector.collector' not in sys.modules", str(cache)],
                         capture_output=True, text=True, env={**os.environ})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["codex"] == {"c1": "busy"}
    assert run(cache, "--session-state") == 0
