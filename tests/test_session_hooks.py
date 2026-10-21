"""Ticket 35: hooks opt-in do Estado da Sessao (Claude), pela CLI, com HOME e CLAUDE_CONFIG_DIR falsos."""
import json
import os
import subprocess
import sys
import time

import pytest

from ai_usage_collector import claude_hooks, session_state
from ai_usage_collector.cli import main


@pytest.fixture
def env(tmp_path):
    cdir = tmp_path / "_sys_claude"  # conftest ja aponta CLAUDE_CONFIG_DIR para ca
    cdir.mkdir()
    assert str(cdir).startswith(str(tmp_path))
    return cdir, tmp_path / "cache" / "status.json", cdir / "settings.json"


def run(cache, *args):
    return main(["--cache-path", str(cache), *args])


def test_nothing_installed_without_command(env):
    cdir, cache, settings = env
    run(cache, "--session-state")
    assert not settings.exists()


def test_install_idempotent_and_preserves_user_config(env, capsys):
    cdir, cache, settings = env
    user = {"theme": "dark", "hooks": {"Stop": [{"matcher": "x", "hooks": [{"type": "command", "command": "echo mine"}]}],
                                       "PreToolUse": []}, "permissions": {"allow": ["Bash(ls)"]}}
    settings.write_text(json.dumps(user, indent=4) + "\n")
    settings.chmod(0o640)
    assert run(cache, "--install-hooks") == 0
    first = settings.read_bytes()
    data = json.loads(first)
    assert set(data["hooks"]) == {"Stop", "PreToolUse", "UserPromptSubmit", "PostToolUse", "Notification"}
    assert data["hooks"]["Stop"][0] == user["hooks"]["Stop"][0] and len(data["hooks"]["Stop"]) == 2
    assert data["theme"] == "dark" and data["permissions"] == user["permissions"]
    assert first.startswith(b'{\n    "theme"') and settings.stat().st_mode & 0o777 == 0o640
    bak = settings.with_name("settings.json.plasma-ai-usage.bak")
    assert json.loads(bak.read_text()) == user and bak.stat().st_mode & 0o777 == 0o600
    assert run(cache, "--install-hooks") == 0
    assert settings.read_bytes() == first
    assert "já estavam" in capsys.readouterr().out
    assert run(cache, "--uninstall-hooks") == 0
    assert json.loads(settings.read_text()) == user  # inclusive o PreToolUse vazio do usuario
    assert run(cache, "--uninstall-hooks") == 0


def test_uninstall_never_touches_lookalikes(env):
    cdir, cache, settings = env
    lookalike = {"type": "command", "command": "x session_state.py busy # plasma-ai-usage"}
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [lookalike]}]}}))
    run(cache, "--install-hooks")
    run(cache, "--uninstall-hooks")
    assert json.loads(settings.read_text()) == {"hooks": {"Stop": [{"hooks": [lookalike]}]}}


def test_missing_and_empty_settings_created_then_removed(env):
    cdir, cache, settings = env
    run(cache, "--install-hooks")
    assert settings.stat().st_mode & 0o777 == 0o600 and not settings.with_name("settings.json.plasma-ai-usage.bak").exists()
    run(cache, "--uninstall-hooks")
    assert json.loads(settings.read_text()) == {}
    settings.write_text("  \n")
    assert run(cache, "--install-hooks") == 0


@pytest.mark.parametrize("content", ["{not json", "[1]", '{"hooks": []}', '{"hooks": {"Stop": {}}}'])
def test_invalid_or_unexpected_settings_aborts_untouched(env, content, capsys):
    cdir, cache, settings = env
    settings.write_text(content)
    assert run(cache, "--install-hooks") == 1
    assert settings.read_text() == content and "Erro" in capsys.readouterr().err
    if content == "{not json":
        assert settings.with_name("settings.json.plasma-ai-usage.bak").read_text() == content


def test_symlink_preserved(env, tmp_path):
    cdir, cache, settings = env
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text('{"a": 1}')
    settings.symlink_to(real)
    assert run(cache, "--install-hooks") == 0
    assert settings.is_symlink() and "hooks" in json.loads(real.read_text())
    assert run(cache, "--uninstall-hooks") == 0 and settings.is_symlink() and json.loads(real.read_text()) == {"a": 1}


def test_concurrent_change_aborts(env, monkeypatch):
    cdir, cache, settings = env
    settings.write_text("{}")
    orig = claude_hooks.add_hooks

    def sneaky(data, state_dir):
        settings.write_text('{"claude": "wrote"}')  # o Claude Code regravou no meio
        return orig(data, state_dir)

    monkeypatch.setattr(claude_hooks, "add_hooks", sneaky)
    assert run(cache, "--install-hooks") == 1
    assert json.loads(settings.read_text()) == {"claude": "wrote"}


def test_hook_command_is_safe_and_real_hook_runs(env, tmp_path):
    cdir, cache, settings = env
    run(cache, "--install-hooks")
    hooks = json.loads(settings.read_text())["hooks"]
    cmd = hooks["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert cmd.endswith(" " + claude_hooks.MARKER) and "|| true" in cmd
    prompt = "SEGREDO-do-prompt " * 10
    stdin = json.dumps({"session_id": "abc-123", "prompt": prompt, "hook_event_name": "UserPromptSubmit"})
    t = time.perf_counter()
    r = subprocess.run(["sh", "-c", cmd], input=stdin, text=True, capture_output=True, env={**os.environ, "CLAUDE_CONFIG_DIR": str(cdir)})
    elapsed = time.perf_counter() - t
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert elapsed < 0.5  # folga para CI; o alvo (<50 ms) e medido a mao
    sdir = cache.parent / "session-state"
    files = list(sdir.glob("*.json"))
    assert len(files) == 1 and "abc-123" not in files[0].name
    assert files[0].stat().st_mode & 0o777 == 0o600 and sdir.stat().st_mode & 0o777 == 0o700
    raw = files[0].read_text()
    assert "SEGREDO" not in raw and "abc-123" not in raw
    assert json.loads(raw)["state"] == "busy" and json.loads(raw)["config_dir"] == str(cdir.resolve())


def test_hook_never_fails_on_garbage(tmp_path):
    for stdin in ("", "{broken", "[1,2]", json.dumps({"session_id": 5})):
        r = subprocess.run([sys.executable, "-I", session_state.__file__, "busy", str(tmp_path / "s")], input=stdin, text=True, capture_output=True)
        assert r.returncode == 0 and r.stdout == ""
    r = subprocess.run([sys.executable, "-I", session_state.__file__, "bogus"], input="{}", text=True, capture_output=True)
    assert r.returncode == 0


def test_idle_prompt_notification_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": __import__("io").BytesIO(b'{"session_id":"s","notification_type":"idle_prompt"}')})())
    session_state.hook_main(["waiting", str(tmp_path / "s")])
    assert not (tmp_path / "s").exists()


def test_aggregation_priority_and_ttl(tmp_path):
    sdir, now = tmp_path / "s", 10_000.0
    session_state.write_event(sdir, "busy", "a", now)
    session_state.write_event(sdir, "idle", "b", now)
    cd = {str(session_state.claude_config_dir())}
    agg = lambda t: session_state.aggregate(session_state.read_sessions(sdir, t), cd)  # noqa: E731
    assert agg(now + 1) == "busy"
    session_state.write_event(sdir, "waiting", "c", now)
    assert agg(now + 1) == "waiting"
    assert agg(now + session_state.TTL_SECONDS + 1) == "unknown"  # sessao morta sem Stop expira
    assert session_state.aggregate(session_state.read_sessions(sdir, now + 1), {"/outro"}) == "unknown"
    (sdir / "lixo.json").write_text("{nope")
    assert agg(now + 1) == "waiting"


def test_contract_exposes_session_state_per_active_account(env):
    from ai_usage_collector.contract import validate_status_contract

    cdir, cache, settings = env
    cfg = cache.parent / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cred = cdir / ".credentials.json"
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "t", "refreshToken": "r", "expiresAt": 9999999999999}}))
    (cdir.parent / ".claude.json").write_text("{}")
    cfg.write_text(json.dumps({"agents": {"claude": {"accounts": [{"id": "p1", "label": "P", "credential_path": str(cred)}]}}}))
    assert run(cache, "--config-path", str(cfg), "--status") == 0
    status = json.loads(cache.read_text())
    assert all("session_state" not in a for a in status["agents"]["claude"]["accounts"])  # sem hooks, sem campo
    session_state.write_event(session_state.state_dir_for(cache), "waiting", "s")
    run(cache, "--config-path", str(cfg), "--refresh")
    status = json.loads(cache.read_text())
    assert validate_status_contract(status)
    states = [a.get("session_state") for a in status["agents"]["claude"]["accounts"]]
    assert states == ["waiting"]
