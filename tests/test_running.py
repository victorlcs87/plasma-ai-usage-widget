"""Ticket 37: processo da CLI em execucao por provedor (/proc simulado) e opcao de ocultar, pela CLI."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from ai_usage_collector import collector, refresh, running
from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config
from ai_usage_collector.contract import CONTRACT_VERSION, validate_status_contract

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(running, "PROC_ROOT", str(proc))
    config_path = tmp_path / "config.json"
    save_config({"version": 1, "agents": {"claude": {"accounts": []}, "codex": {"accounts": []},
                                          "gemini": {"accounts": []}}}, config_path)
    cache_path = tmp_path / "cache" / "status.json"
    clock = {"now": T0}
    monkeypatch.setattr(refresh, "utcnow", lambda: clock["now"])
    monkeypatch.setattr(running, "utcnow", lambda: clock["now"])
    base = ["--config-path", str(config_path), "--cache-path", str(cache_path)]

    class E:
        pass

    e = E()
    e.proc, e.base, e.cache, e.clock = proc, base, cache_path, clock

    def spawn(pid, *argv):
        d = proc / str(pid)
        d.mkdir(exist_ok=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")

    def status():
        s = json.loads(cache_path.read_text())
        assert validate_status_contract(s)
        return s

    def flags():
        return {p: a.get("running", "ausente") for p, a in status()["agents"].items()}

    e.spawn, e.status, e.flags = spawn, status, flags
    spawn(1, "systemd")  # um processo nosso sempre existe em /proc de verdade
    assert main(["--refresh", *base]) == 0
    return e


def test_flags_reflect_strict_process_match(env):
    assert env.flags() == {"claude": False, "codex": False, "gemini": False}
    env.spawn(10, "claude", "--resume")
    env.spawn(11, "node", "/usr/lib/node_modules/@google/gemini-cli/bin/gemini", "-m", "x")
    env.spawn(12, "/home/u/.local/bin/codex")
    env.clock["now"] += timedelta(minutes=1)
    assert main(["--detect-running", *env.base]) == 0
    assert env.flags() == {"claude": True, "codex": True, "gemini": True}
    assert env.status()["version"] == CONTRACT_VERSION == 5  # campo opcional: sem bump


@pytest.mark.parametrize("argv", [
    ("claude-code-widget",),
    ("ai-usage-collector", "--refresh", "--provider", "claude"),
    ("python3", "-m", "ai_usage_collector", "--refresh", "claude"),
    ("nvim", "/home/u/claude/notes.md"),
    ("/usr/bin/plasmashell", "--claude"),
    ("node", "--inspect", "claude"),
    ("node", "/home/u/projects/claude/server.js"),
    ("claudette",),
    ("my claude",),
    (),
])
def test_false_positives_are_not_running(env, argv):
    env.spawn(20, *argv)
    env.clock["now"] += timedelta(minutes=1)
    main(["--detect-running", *env.base])
    assert env.flags()["claude"] is False


def test_only_own_processes_count(env, monkeypatch):
    env.spawn(30, "claude")
    real = os.stat

    def stat(path, *a, **k):
        r = real(path, *a, **k)
        if str(path).endswith("/30"):  # dono diferente
            return os.stat_result((r.st_mode, r.st_ino, r.st_dev, r.st_nlink, r.st_uid + 1, *tuple(r)[5:]))
        return r

    monkeypatch.setattr(os, "stat", stat)
    env.clock["now"] += timedelta(minutes=1)
    main(["--detect-running", *env.base])
    assert env.flags()["claude"] is False


def test_vanishing_process_is_ignored(env, monkeypatch):
    env.spawn(40, "claude")
    real = open

    def flaky(path, *a, **k):
        if str(path).endswith("40/cmdline"):
            raise FileNotFoundError(path)
        return real(path, *a, **k)

    monkeypatch.setattr("builtins.open", flaky)
    env.clock["now"] += timedelta(minutes=1)
    main(["--detect-running", *env.base])
    monkeypatch.undo()
    assert env.flags()["claude"] is False  # sumiu: nao ha o que contar, nem erro


def test_unreadable_own_process_makes_absence_unknown_but_not_presence(env, monkeypatch):
    env.spawn(50, "codex")
    env.spawn(51, "whatever")
    real = open

    def denied(path, *a, **k):
        if str(path).endswith("51/cmdline"):
            raise PermissionError(path)
        return real(path, *a, **k)

    monkeypatch.setattr("builtins.open", denied)
    env.clock["now"] += timedelta(minutes=1)
    main(["--detect-running", *env.base])
    monkeypatch.undo()
    assert env.flags() == {"claude": None, "codex": True, "gemini": None}


def test_missing_or_empty_proc_is_unknown_never_false(env, tmp_path, monkeypatch):
    monkeypatch.setattr(running, "PROC_ROOT", str(tmp_path / "nao-existe"))
    env.clock["now"] += timedelta(minutes=1)
    main(["--detect-running", *env.base])
    assert env.flags() == {"claude": None, "codex": None, "gemini": None}
    (tmp_path / "vazio").mkdir()
    monkeypatch.setattr(running, "PROC_ROOT", str(tmp_path / "vazio"))  # /proc sem nenhum processo nosso
    env.clock["now"] += timedelta(minutes=1)
    main(["--detect-running", *env.base])
    assert env.flags() == {"claude": None, "codex": None, "gemini": None}


def test_detection_is_cached_briefly(env, monkeypatch):
    env.spawn(60, "claude")
    calls = []
    real = running.detect_running
    monkeypatch.setattr(running, "detect_running", lambda *a, **k: calls.append(1) or real(*a, **k))
    env.clock["now"] += timedelta(seconds=30)
    for _ in range(3):
        main(["--detect-running", *env.base])
    assert len(calls) == 1 and env.flags()["claude"] is True
    env.clock["now"] += timedelta(seconds=running.CACHE_SECONDS + 1)
    main(["--detect-running", *env.base])
    assert len(calls) == 2


def test_detect_without_status_is_noop(tmp_path):
    assert main(["--detect-running", "--config-path", str(tmp_path / "c.json"), "--cache-path", str(tmp_path / "s.json")]) == 0
    assert not (tmp_path / "s.json").exists()


def test_visibility_config_default_off_validated_and_exposed(env):
    assert env.status()["visibility"] == {"hide_when_not_running": "off"}
    assert main(["--set-visibility-config", "--hide-when-not-running", "widget", *env.base]) == 0
    assert env.status()["visibility"] == {"hide_when_not_running": "widget"}
    assert json.loads(open(env.base[1]).read())["visibility"] == {"hide_when_not_running": "widget"}
    with pytest.raises(SystemExit):
        main(["--set-visibility-config", "--hide-when-not-running", "tudo", *env.base])
    assert env.status()["visibility"]["hide_when_not_running"] == "widget"
    assert main(["--set-visibility-config", *env.base]) == 1  # nada informado


def test_set_visibility_does_not_rescan_or_collect(env, monkeypatch):
    monkeypatch.setattr(running, "detect_running", lambda *a, **k: pytest.fail("nao deve varrer"))
    assert main(["--set-visibility-config", "--hide-when-not-running", "provider", *env.base]) == 0


def test_invalid_stored_mode_falls_back_to_off(env):
    cfg = json.load(open(env.base[1]))
    cfg["visibility"] = {"hide_when_not_running": "banana"}
    save_config(cfg, env.base[1])
    assert running.visibility_settings(cfg) == {"hide_when_not_running": "off"}


def test_contract_rejects_bad_running_values(env):
    s = env.status()
    s["agents"]["claude"]["running"] = "yes"
    assert not validate_status_contract(s)
    s["agents"]["claude"]["running"] = None
    s["visibility"] = {"hide_when_not_running": "x"}
    assert not validate_status_contract(s)


# --- Plasmoid (NotchModel.js em qml6; opcional) e fiacao estatica ---
import shutil
import subprocess
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui"


def _qml_eval(tmp_path, expr):
    shutil.copy(UI / "NotchModel.js", tmp_path / "NotchModel.js")
    shutil.copy(UI / "Presets.js", tmp_path / "Presets.js")
    (tmp_path / "t.qml").write_text(
        'import QtQuick\nimport "NotchModel.js" as N\nItem { Component.onCompleted: { '
        f'console.log("OUT " + JSON.stringify({expr})); Qt.quit() }} }}')
    out = subprocess.run(["qml6", str(tmp_path / "t.qml")], capture_output=True, text=True, timeout=30,
                         env=dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1"))
    out = out.stdout + out.stderr
    return json.loads(out.split("OUT ", 1)[1].splitlines()[0])


@pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")
def test_notch_hides_only_on_explicit_false_and_fresh(tmp_path):
    fresh = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    def st(mode, flags, checked=fresh):
        return {"visibility": {"hide_when_not_running": mode}, "running_checked_at": checked,
                "agents": {p: {"name": p, "accounts": [], **({} if v == "ausente" else {"running": v})} for p, v in flags.items()}}

    cfg = {"providerOrder": "claude,codex,gemini", "hiddenProviders": ""}
    f = {"claude": False, "codex": False, "gemini": False}
    cases = {
        "off": st("off", f), "widget_all_false": st("widget", f), "widget_one_true": st("widget", {**f, "codex": True}),
        "widget_null": st("widget", {**f, "codex": None}), "widget_absent": st("widget", {**f, "codex": "ausente"}),
        "widget_stale": st("widget", f, old), "widget_nodate": st("widget", f, None),
    }
    got = _qml_eval(tmp_path, "(function(){ var r={}; var c=%s; var cfg=%s; for (var k in c) r[k]=N.widgetIdle(c[k], cfg); "
                              "r.nodata = N.widgetIdle(null, cfg); return r })()" % (json.dumps(cases), json.dumps(cfg)))
    assert got == {"off": False, "widget_all_false": True, "widget_one_true": False, "widget_null": False,
                   "widget_absent": False, "widget_stale": False, "widget_nodate": False, "nodata": False}
    only_claude = {**cfg, "hiddenProviders": "codex,gemini"}
    prov = st("provider", {**f, "codex": True})
    names = _qml_eval(tmp_path, "N.buildModel(%s, %s, function(t){return t}).map(function(m){return m.provider})"
                      % (json.dumps(prov), json.dumps(cfg)))
    assert names == ["codex"]  # provedor parado some, o que roda fica
    assert _qml_eval(tmp_path, "N.widgetIdle(%s, %s)" % (json.dumps(st("widget", f)), json.dumps(only_claude))) is True
    assert _qml_eval(tmp_path, "N.buildModel(%s, %s, function(t){return t}).length"
                     % (json.dumps({**prov, "running_checked_at": old}), json.dumps(cfg))) == 3


def test_plasmoid_wiring_and_recovery_path():
    main, compact, config = ((UI / n).read_text() for n in ("main.qml", "CompactRepresentation.qml", "configGeneral.qml"))
    assert "Plasmoid.status: root.idleHidden ? PlasmaCore.Types.PassiveStatus : PlasmaCore.Types.ActiveStatus" in main
    assert "HiddenStatus" not in main  # Hidden removeria a via de volta; Passive mantem o widget alcancavel
    assert "!root.expanded && !Plasmoid.userConfiguring" in main  # abrir popup/configuracao sempre mostra
    assert '"--detect-running"' in main and 'NotchModel.hideMode(root.statusData) !== "off"' in main
    assert "sliver" in compact and "MouseArea" in compact  # no painel resta um alvo para o botao direito
    assert '"--set-visibility-config"' in config and '"--hide-when-not-running"' in config
