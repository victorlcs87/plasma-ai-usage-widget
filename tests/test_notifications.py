"""Notificacoes de limite (ticket 25) pela CLI, com relogio, leituras e transporte D-Bus falsos."""

import json
import multiprocessing
import os
import stat
import subprocess
from datetime import timedelta

import pytest

from ai_usage_collector import notifications, refresh
from ai_usage_collector.cli import main
from ai_usage_collector.contract import CONTRACT_VERSION, validate_status_contract
from test_pace import T0, env  # noqa: F401  (fixture)

FAR = T0 + timedelta(days=30)


def configure(env, *args):  # noqa: F811
    assert main(["--set-notify-config", *args, *env.base]) == 0


def test_threshold_notice_fires_once_per_window(env, notified):
    configure(env, "--notify-early", "off")
    env(minutes=0, native=50.0)
    assert notified == []
    env(minutes=1, native=82.0)
    env(minutes=2, native=83.0)
    env(minutes=3, native=84.0)
    assert len(notified) == 1 and "82%" in notified[0][0] and not notified[0][2]
    env(minutes=4, native=82.5)
    env(minutes=5, native=96.0)
    assert len(notified) == 2 and notified[1][2] is True  # critico: urgencia alta


def test_jump_straight_to_critical_sends_only_critical_and_no_late_warning(env, notified):
    env(minutes=0, native=50.0)
    env(minutes=1, native=97.0)
    env(minutes=2, native=98.0)
    assert len(notified) == 1 and notified[0][2] is True


def test_configurable_thresholds_are_validated_like_alert_config(env, notified):
    configure(env, "--notify-warning", "60", "--notify-critical", "90")
    env(minutes=0, native=65.0)
    assert len(notified) == 1
    for bad in (["--notify-warning", "95", "--notify-critical", "90"], ["--notify-critical", "101"],
                ["--notify-warning", "nan"], ["--notify-warning", "0"], ["--notify-mute", "foo"]):
        assert main(["--set-notify-config", *bad, *env.base]) == 1
    cfg = json.loads(env.config_path.read_text())["notifications"]
    assert cfg["warning"] == 60 and cfg["critical"] == 90


def test_muted_provider_gets_nothing_and_unmuting_does_not_burst(env, notified):
    new = {"release_native": T0 + timedelta(hours=10)}
    configure(env, "--notify-mute", "claude", "--notify-reset", "on")
    env(minutes=0, native=85.0, weekly=96.0)
    env(minutes=301, native=5.0, **new)  # reset de limite sinalizado
    env(minutes=302, native=85.0, **new)
    assert notified == []
    configure(env, "--notify-mute", "")
    env(minutes=303, native=86.0, **new)  # o ciclo ja consumiu o aviso
    assert notified == []


def test_early_warning_native_once_per_window(env, notified):
    configure(env, "--notify-warning", "90", "--notify-critical", "99")
    env(minutes=0, native=10.0)
    env(minutes=10, native=40.0)
    env(minutes=20, native=70.0)  # 3%/min: 100% em 10 min, antes da liberacao
    env(minutes=21, native=73.0)
    env(minutes=22, native=76.0)
    assert len(notified) == 1 and "min" in notified[0][0]


def test_early_warning_weekly_horizon_is_24h(env, notified):
    far = {"release_native": FAR}
    env(minutes=0, weekly=10.0, **far)
    env(minutes=360, weekly=40.0, **far)
    env(minutes=720, weekly=70.0, **far)  # 5%/h: esgota em 6 h
    env(minutes=730, weekly=71.0, **far)
    assert len(notified) == 1 and "semanal" in notified[0][0].lower()


def test_no_early_warning_when_forecast_is_beyond_horizon_or_after_release(env, notified):
    env(minutes=0, native=10.0)
    env(minutes=10, native=11.0)
    env(minutes=20, native=12.0)  # 0,1%/min: esgota em ~14 h
    assert notified == []
    soon = {"release_native": T0 + timedelta(minutes=35)}
    env(minutes=30, native=40.0, **soon)  # libera antes de esgotar
    env(minutes=31, native=43.0, **soon)
    assert notified == []


def test_early_warning_can_be_disabled(env, notified):
    configure(env, "--notify-early", "off", "--notify-warning", "90", "--notify-critical", "99")
    for m, p in ((0, 10.0), (10, 40.0), (20, 70.0), (21, 73.0)):
        env(minutes=m, native=p)
    assert notified == []


def test_reset_notice_only_for_flagged_limit_and_when_enabled(env, notified):
    new = {"release_native": T0 + timedelta(hours=10)}
    env(minutes=0, native=85.0, weekly=20.0)
    env(minutes=301, native=5.0, **new)  # desabilitado por padrao
    assert len(notified) == 1
    configure(env, "--notify-reset", "on")
    env(minutes=302, native=85.0, **new)  # sinaliza de novo no ciclo novo
    assert len(notified) == 2
    later = {"release_native": T0 + timedelta(hours=20), "weekly": 2.0}
    env(minutes=700, native=3.0, **later)
    assert len(notified) == 3 and "liberad" in notified[2][0].lower()
    env(minutes=701, native=3.0, **later)
    assert len(notified) == 3  # reset nao repete; semanal nunca sinalizado nao avisa


def test_new_cycle_reenables_warnings(env, notified):
    env(minutes=0, native=85.0)
    env(minutes=1, native=86.0)
    assert len(notified) == 1
    env(minutes=301, native=85.0, release_native=T0 + timedelta(hours=10))
    assert len(notified) == 2


def test_release_jitter_is_still_the_same_cycle(env, notified):
    env(minutes=0, native=85.0)
    env(minutes=1, native=86.0, release_native=T0 + timedelta(hours=5, seconds=7))
    assert len(notified) == 1


def test_local_reading_never_notifies(env, notified):
    env(minutes=0, native=99.0, weekly=99.0, source="local")
    assert notified == []


@pytest.mark.parametrize("flag", ["stale", "no_data"])
def test_stale_or_no_data_never_notifies(env, notified, monkeypatch, flag):
    monkeypatch.setattr(refresh, "apply_outcome", lambda acc, *a, **k: acc.update({flag: True}))
    env(minutes=0, native=99.0, weekly=99.0)
    assert notified == []


def test_send_failure_does_not_break_collection_and_is_retried(env, notified):
    notified.ok = False
    env(minutes=0, native=85.0)
    assert notified == []
    notified.ok = True
    env(minutes=1, native=86.0)
    assert len(notified) == 1
    notified.boom = True
    env(minutes=2, native=97.0)  # excecao do transporte: coleta segue
    assert len(notified) == 1
    notified.boom = False
    env(minutes=3, native=97.0)
    assert len(notified) == 2


def test_untrusted_label_is_plain_and_clean(env, notified):
    cfg = json.loads(env.config_path.read_text())
    cfg["agents"]["claude"]["accounts"][0]["label"] = "<b>x</b>\x1b[31m&\n--evil " + "y" * 300
    env.config_path.write_text(json.dumps(cfg))
    env(minutes=0, native=85.0)
    body = notified[0][1]
    assert "<b>" not in body and "\x1b" not in body and "\n" not in body and "&lt;b&gt;" in body and len(body) < 200


def test_cache_is_private_atomic_and_tolerates_corruption(env, notified):
    state = env.cache_path.with_name("notified.json")
    for junk in ("{nao json", "[]", '{"windows": 5}',
                 '{"windows": {"claude:a:native": {"release": "x", "sent": 3, "seen": null}, "k": 1}}'):
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(junk)
        notified.clear()
        env(minutes=0, native=85.0)
        assert len(notified) == 1
        assert stat.S_IMODE(os.stat(state).st_mode) == 0o600
        json.loads(state.read_text())
        state.unlink()


def test_backwards_clock_does_not_repeat_and_state_is_pruned(env, notified):
    env(minutes=10, native=85.0)
    env(minutes=0, native=86.0)  # relogio recuado
    assert len(notified) == 1
    state = env.cache_path.with_name("notified.json")
    data = json.loads(state.read_text())
    stale = {"release": 1.0, "sent": ["warning"], "seen": (T0 - timedelta(days=30)).timestamp()}
    data["windows"]["codex:old:native"] = stale  # antigo, de Conta que nao existe mais
    data["windows"]["claude:removed:weekly"] = {**stale, "seen": T0.timestamp()}  # Conta removida
    state.write_text(json.dumps(data))
    env(minutes=11, native=86.0)
    assert set(json.loads(state.read_text())["windows"]) == {"claude:a:native", "claude:a:weekly"}


def _collect(args, q):
    q.put(main(args))


def test_concurrent_collectors_notify_once(env, notified, tmp_path, monkeypatch):
    env(minutes=0, native=10.0)
    log = tmp_path / "sent.log"

    def to_file(summary, body, critical=False):
        with log.open("a") as f:
            f.write(summary + "\n")
        return True

    monkeypatch.setattr(notifications, "dbus_notify", to_file)
    env.state["native"] = 85.0
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    procs = [ctx.Process(target=_collect, args=(["--refresh", *env.base], q)) for _ in range(4)]
    [p.start() for p in procs]
    [p.join(30) for p in procs]
    assert [q.get(timeout=5) for _ in procs] == [0] * 4
    assert len(log.read_text().splitlines()) == 1


def test_status_exposes_settings_and_keeps_contract_version(env):
    configure(env, "--notify-mute", "codex,gemini", "--notify-reset", "on")
    env(minutes=0)
    status = json.loads(env.cache_path.read_text())
    assert status["notifications"] == {"warning": 80.0, "critical": 95.0, "early": True, "reset": True,
                                       "muted": ["codex", "gemini"]}
    assert status["version"] == CONTRACT_VERSION == 5 and validate_status_contract(status)
    status["notifications"]["muted"] = "x"
    assert not validate_status_contract(status)


def test_set_notify_config_updates_existing_status_without_collecting(env):
    env(minutes=0)
    calls = env.state["calls"]
    configure(env, "--notify-warning", "50")
    assert env.state["calls"] == calls
    assert json.loads(env.cache_path.read_text())["notifications"]["warning"] == 50


def test_real_transport_uses_argument_list_without_shell(notified, monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent")
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, kw=kw)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert notified.real("-h evil; rm -rf ~", "$(touch x) `y`", critical=True)
    cmd = seen["cmd"]
    assert isinstance(cmd, list) and cmd[0] == "notify-send" and cmd[-3] == "--"
    assert cmd[-2:] == ["-h evil; rm -rf ~", "$(touch x) `y`"] and "--urgency=critical" in cmd
    assert not seen["kw"].get("shell") and seen["kw"]["timeout"] > 0

    def boom(exc):
        def run(*a, **k):
            raise exc
        return run

    for exc in (FileNotFoundError(), subprocess.TimeoutExpired("n", 1), OSError()):
        monkeypatch.setattr(subprocess, "run", boom(exc))
        assert notified.real("a", "b") is False
    monkeypatch.setattr(subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 1))
    assert notified.real("a", "b") is False


def test_real_transport_skips_notify_send_without_session_bus(notified, monkeypatch, tmp_path):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("autolaunch do dbus-daemon"))
    assert notified.real("a", "b") is False


def test_delivery_runs_outside_the_lock_and_stops_after_first_failure(env, notified, monkeypatch):
    import fcntl
    import time

    lock = env.cache_path.with_name("refresh_state.lock")
    calls, free = [], []

    def slow_fail(summary, body, critical=False):
        calls.append(summary)
        fd = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # lock liberado durante o envio
            free.append(True)
        except BlockingIOError:
            free.append(False)
        finally:
            os.close(fd)
        time.sleep(0.2)
        return False

    monkeypatch.setattr(notifications, "dbus_notify", slow_fail)
    start = time.monotonic()
    env(minutes=0, native=96.0, weekly=96.0)  # dois avisos devidos
    assert len(calls) == 1 and free == [True]  # parou no primeiro erro
    assert time.monotonic() - start < 1.5
    assert json.loads(env.cache_path.read_text())["agents"]["claude"]["accounts"][0]  # status salvo
    monkeypatch.setattr(notifications, "dbus_notify", notified)
    env(minutes=1, native=96.0, weekly=96.0)  # nao entregues foram desmarcados: tenta de novo
    assert len(notified) == 2


def test_notices_per_cycle_are_capped_and_rest_goes_next_cycle(env, notified, monkeypatch):
    monkeypatch.setattr(notifications, "MAX_PER_CYCLE", 1)
    env(minutes=0, native=96.0, weekly=96.0)
    assert len(notified) == 1
    env(minutes=1, native=96.0, weekly=96.0)
    assert len(notified) == 2
    env(minutes=2, native=96.0, weekly=96.0)
    assert len(notified) == 2


def test_one_invalid_field_keeps_muted_and_the_other_fields(env, notified):
    configure(env, "--notify-mute", "claude,codex", "--notify-reset", "on")
    cfg = json.loads(env.config_path.read_text())
    cfg["notifications"].update(warning="abc", early="sim")
    env.config_path.write_text(json.dumps(cfg))
    env(minutes=0, native=99.0)
    assert notified == []  # claude segue silenciado
    n = json.loads(env.cache_path.read_text())["notifications"]
    assert n["muted"] == ["claude", "codex"] and n["reset"] is True and n["warning"] == 80.0 and n["early"] is True


def test_invalid_alert_threshold_keeps_alert_mode(env):
    cfg = json.loads(env.config_path.read_text())
    cfg["alerts"] = {"mode": "threshold", "warning": 99, "critical": 10}
    env.config_path.write_text(json.dumps(cfg))
    env(minutes=0)
    assert json.loads(env.cache_path.read_text())["alerts"] == {"mode": "threshold", "warning": 70.0, "critical": 90.0}


def test_state_write_failure_is_reported_and_does_not_break_or_send(env, notified, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disco cheio")

    monkeypatch.setattr(notifications, "save_secure_json", boom)
    env(minutes=0, native=96.0)
    assert notified == [] and "nao gravados" in capsys.readouterr().err


def test_contract_rejects_non_string_muted(env):
    env(minutes=0)
    status = json.loads(env.cache_path.read_text())
    status["notifications"]["muted"] = [1]
    assert not validate_status_contract(status)


def test_failed_delivery_warns_once_until_a_send_succeeds(env, notified, capsys):
    notified.ok = False
    env(minutes=0, native=96.0)
    assert "notify-send" in capsys.readouterr().err
    env(minutes=1, native=96.0)  # tenta de novo, mas sem repetir o aviso
    assert capsys.readouterr().err == ""
    notified.ok = True
    env(minutes=2, native=96.0)
    assert len(notified) == 1 and not env.cache_path.with_name("notify_failed").exists()
    notified.ok = False
    env(minutes=400, native=5.0, release_native=T0 + timedelta(hours=10))
    env(minutes=401, native=96.0, release_native=T0 + timedelta(hours=10))
    assert "notify-send" in capsys.readouterr().err  # nova falha depois de um sucesso volta a avisar
