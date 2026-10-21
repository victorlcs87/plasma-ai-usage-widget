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


def hook(monkeypatch, tmp_path, state, stdin: bytes):
    import threading

    r, w = os.pipe()

    def feed():
        with os.fdopen(w, "wb") as f:
            try:
                f.write(stdin)
            except BrokenPipeError:
                pass

    t = threading.Thread(target=feed)
    t.start()
    try:
        assert session_state.hook_main([state, str(tmp_path / "s")], fd=r) == 0
    finally:
        os.close(r)
        t.join()
    return session_state.read_sessions(tmp_path / "s")


@pytest.mark.parametrize("ntype", ["idle_prompt", "auth_success", "algo_novo", None])
def test_notification_only_waits_for_allowed_types(tmp_path, monkeypatch, ntype):
    payload = {"session_id": "s", **({"notification_type": ntype} if ntype else {})}
    assert hook(monkeypatch, tmp_path, "waiting", json.dumps(payload).encode()) == []


@pytest.mark.parametrize("ntype", session_state.WAITING_NOTIFICATION_TYPES)
def test_notification_allowed_types_wait(tmp_path, monkeypatch, ntype):
    recs = hook(monkeypatch, tmp_path, "waiting", json.dumps({"session_id": "s", "notification_type": ntype}).encode())
    assert [r["state"] for r in recs] == ["waiting"]


def test_huge_stdin_still_records_state_and_is_drained(tmp_path, monkeypatch):
    # PostToolUse com tool_response enorme: JSON truncado no prefixo, mas o estado e gravado
    big = b'{"session_id": "abc-1", "tool_response": "' + b"x" * (3 << 20) + b'"}'
    recs = hook(monkeypatch, tmp_path, "busy", big)
    assert [r["state"] for r in recs] == ["busy"]


def test_huge_stdin_real_process_no_epipe(tmp_path):
    big = b'{"session_id": "abc-1", "notification_type": "permission_prompt", "p": "' + b"y" * (5 << 20) + b'"}'
    r = subprocess.run([sys.executable, "-I", session_state.__file__, "waiting", str(tmp_path / "s")], input=big, capture_output=True)
    assert r.returncode == 0 and r.stderr == b""
    assert [x["state"] for x in session_state.read_sessions(tmp_path / "s")] == ["waiting"]


def test_only_root_level_fields_count(tmp_path, monkeypatch):
    # session_id/notification_type dentro do prompt ou de objetos aninhados nunca valem
    evil = json.dumps({"prompt": '"session_id": "forjado", "notification_type": "permission_prompt"', "x": {"session_id": "aninhado"},
                       "session_id": "real"}).encode()
    assert hook(monkeypatch, tmp_path, "busy", evil) and (tmp_path / "s" / (session_state.hashlib.sha256(b"real").hexdigest()[:16] + ".json")).exists()
    forged = b'{"prompt": "\\"notification_type\\": \\"permission_prompt\\"", "session_id": "q"' + b", " + b'"big": "' + b"z" * (2 << 20)
    assert hook(monkeypatch, tmp_path / "w", "waiting", forged) == []


@pytest.mark.parametrize("mode", ["open", "drip"])
def test_stdin_left_open_does_not_hang_hook(tmp_path, mode):
    import time as _t

    p = subprocess.Popen([sys.executable, "-I", session_state.__file__, "busy", str(tmp_path / "s")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = _t.monotonic()
    p.stdin.write(b'{"session_id": "abc", "p": "')
    p.stdin.flush()
    if mode == "drip":
        while p.poll() is None and _t.monotonic() - t0 < 6:
            try:
                p.stdin.write(b"x" * 10)
                p.stdin.flush()
            except BrokenPipeError:
                break
            _t.sleep(0.2)
    out, err = p.communicate(timeout=6) if mode == "drip" else (p.wait(timeout=6), None)[::1]
    assert p.returncode == 0 and _t.monotonic() - t0 <= 3.0
    assert [r["state"] for r in session_state.read_sessions(tmp_path / "s")] == ["busy"]


def test_accounts_map_failure_keeps_contract_field(tmp_path):
    cache = tmp_path / "c" / "status.json"
    (cache.parent / session_state.ACCOUNTS_FILENAME).mkdir(parents=True)  # os.replace vai falhar
    session_state.write_event(session_state.state_dir_for(cache), "busy", "s")
    status = {"agents": {"claude": {"accounts": [{"id": "a", "isActive": True}]}}}
    session_state.apply_session_state(status, {}, cache)
    assert status["agents"]["claude"]["accounts"][0]["session_state"] == "busy"


def test_truncated_prefix_ignores_unsafe_session_id(tmp_path, monkeypatch):
    bad = b'{"session_id": "../../etc x", "p": "' + b"z" * (2 << 20)
    assert [r["state"] for r in hook(monkeypatch, tmp_path, "busy", bad)] == ["busy"]  # cai em "unknown", nunca no id cru
    assert [f.name for f in (tmp_path / "s").glob("*.json")] == [session_state.hashlib.sha256(b"unknown").hexdigest()[:16] + ".json"]


def test_existing_state_dir_tightened_and_orphan_tmp_purged(tmp_path):
    sdir = tmp_path / "s"
    sdir.mkdir(mode=0o755)
    orphan = sdir / ".dead.1.tmp"
    orphan.write_text("x")
    os.utime(orphan, (1, 1))
    session_state.write_event(sdir, "busy", "a")
    assert sdir.stat().st_mode & 0o777 == 0o700 and not orphan.exists()


def test_aggregation_priority_and_ttl(tmp_path):
    sdir, now = tmp_path / "s", 10_000.0
    session_state.write_event(sdir, "busy", "a", now)
    session_state.write_event(sdir, "idle", "b", now)
    cd = {str(session_state.claude_config_dir())}
    agg = lambda t: session_state.aggregate(session_state.read_sessions(sdir, t), cd)  # noqa: E731
    assert agg(now + 1) == "busy"
    session_state.write_event(sdir, "waiting", "c", now)
    assert agg(now + 1) == "waiting"
    assert agg(now + session_state.TTL_SECONDS["busy"] + 1) == "idle"  # ocupada/aguardando sem evento expiram em minutos
    assert agg(now + session_state.TTL_SECONDS["idle"] + 1) == "unknown"  # a ociosa dura mais, mas tambem expira
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


def test_surrogate_in_settings_aborts_without_backup(env, capsys):
    cdir, cache, settings = env
    content = '{"x": "\\ud800"}'
    settings.write_text(content)
    assert run(cache, "--install-hooks") == 1
    assert settings.read_text() == content and "UTF-8" in capsys.readouterr().err
    assert not settings.with_name("settings.json.plasma-ai-usage.bak").exists()


def test_is_ours_requires_script_name():
    assert not claude_hooks.is_ours({"command": "echo " + claude_hooks.MARKER})
    assert not claude_hooks.is_ours({"command": 7}) and not claude_hooks.is_ours("x")


def test_relative_claude_config_dir_refused(env, monkeypatch, capsys):
    cdir, cache, settings = env
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "relativo")
    assert run(cache, "--install-hooks") == 1 and "absoluto" in capsys.readouterr().err


def test_malformed_accounts_tolerated(tmp_path):
    for status in ({"agents": []}, {"agents": {"claude": {"accounts": [1, "x", None, {"id": "a"}]}}}, {"agents": {"claude": 5}}):
        session_state.apply_session_state(status, {}, tmp_path / "status.json")
    # --session-state le mapa quebrado/ausente sem erro
    (tmp_path / session_state.ACCOUNTS_FILENAME).write_text('["lista"]')
    assert session_state.live_states(tmp_path / "status.json") == {}
    assert run(tmp_path / "status.json", "--session-state") == 0


def test_light_path_matches_contract_and_imports_no_collector(env):
    cdir, cache, settings = env
    status = {"agents": {"claude": {"accounts": [{"id": "a", "isActive": True}]}}}
    session_state.apply_session_state(status, {}, cache)
    session_state.write_event(session_state.state_dir_for(cache), "busy", "s")
    assert session_state.live_states(cache) == {"a": "busy"}
    r = subprocess.run([sys.executable, "-I", "-c", "import sys, ai_usage_collector.session_state as m; m.states_main([sys.argv[1]]); "
                        "assert 'ai_usage_collector.collector' not in sys.modules", str(cache)],
                       capture_output=True, text=True, env={**os.environ, "CLAUDE_CONFIG_DIR": str(cdir)})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"claude": {"a": "busy"}, "codex": {}}
