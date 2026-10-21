"""Ritmo de Uso, Previsao de Esgotamento e nivel de alerta, pela CLI com relogio e leituras falsos."""

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from ai_usage_collector import collector, refresh
from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config
from ai_usage_collector.contract import validate_status_contract

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
NATIVE_S, WEEK_S = 18000, 604800


@pytest.fixture
def env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    save_config({"version": 1, "agents": {"claude": {"accounts": [{"id": "a", "label": "A", "source": "manual"}]},
                                          "codex": {"accounts": []}, "gemini": {"accounts": []}}}, config_path)
    cache_path = tmp_path / "cache" / "status.json"
    clock = {"now": T0}
    # pct/release por janela; release None = 5h/7d a partir de T0
    state = {"native": 10.0, "weekly": 10.0, "source": "api", "release_native": T0 + timedelta(hours=5),
             "release_weekly": T0 + timedelta(days=7), "health": "valid"}

    def win(kind):
        total, rel = (NATIVE_S, state["release_native"]) if kind == "native" else (WEEK_S, state["release_weekly"])
        key = "release_time" if kind == "native" else "cycle_reset_time"
        return {"window_seconds": total, key: rel.isoformat(), "usage_percentage": state[kind],
                "seconds_remaining": max(0, int((rel - clock["now"]).total_seconds())), "source": state["source"]}

    monkeypatch.setattr(collector, "extract_claude_status", lambda acc, initial_health=None, now=None, **kw: {
        "health": {"status": state["health"]}, "native_window": win("native"), "weekly_window": win("weekly")})
    monkeypatch.setattr(collector, "apply_token_history", lambda *a, **k: None)
    monkeypatch.setattr(refresh, "utcnow", lambda: clock["now"])

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(collector, "datetime", FakeDatetime)
    base = ["--config-path", str(config_path), "--cache-path", str(cache_path)]

    def run(minutes=0, **changes):
        state.update(changes)
        clock["now"] = T0 + timedelta(minutes=minutes)
        assert main(["--refresh", *base]) == 0
        status = json.loads(cache_path.read_text())
        assert validate_status_contract(status)
        return status["agents"]["claude"]["accounts"][0]

    run.base, run.state, run.samples = base, state, cache_path.with_name("samples.json")
    run.cache_path, run.config_path = cache_path, config_path
    return run


def test_pace_and_level_in_pace_mode(env):
    # 1h de 5h decorrida (20%): 30% consumido => ritmo 1.5, esgota antes da liberacao
    acc = env(minutes=60, native=30.0)
    assert acc["native_window"]["pace"] == 1.5
    assert acc["native_window"]["alert_level"] == "warning"
    # semanal: so 0.6% decorrido, cedo demais para ritmo
    assert acc["weekly_window"]["alert_level"] is None


def test_weekly_pace_normal_when_slow(env):
    acc = env(minutes=50 * 60, weekly=10.0)  # 30% decorrido, 10% consumido
    assert acc["weekly_window"]["pace"] == 0.34 and acc["weekly_window"]["alert_level"] == "normal"


def test_pace_critical_when_near_limit_and_exhausting(env):
    assert env(minutes=60, native=92.0)["native_window"]["alert_level"] == "critical"


def test_pace_too_early_in_window_has_no_level(env):
    acc = env(minutes=1, native=5.0)  # 0.3% decorrido
    assert "pace" not in acc["native_window"] and acc["native_window"]["alert_level"] is None


def test_forecast_native_uses_last_30_minutes(env):
    env(minutes=0, native=10.0)
    env(minutes=10, native=20.0)
    fc = env(minutes=20, native=30.0)["native_window"]["forecast"]
    assert fc["seconds_until"] == 70 * 60  # 1%/min => 70 min restantes
    assert fc["before_release"] is True and fc["basis_seconds"] == 1200
    assert fc["exhausts_at"] == (T0 + timedelta(minutes=90)).isoformat()


def test_forecast_drops_samples_older_than_lookback(env):
    env(minutes=0, native=10.0)
    env(minutes=40, native=20.0)
    # a amostra de 0 min (>30 min) cai: so restam as de 40 e 60 min
    fc = env(minutes=60, native=40.0)["native_window"]["forecast"]
    assert fc["basis_seconds"] == 1200 and fc["seconds_until"] == 60 * 60


def test_weekly_forecast_uses_24h(env):
    env(minutes=0, weekly=10.0)
    fc = env(minutes=12 * 60, weekly=40.0)["weekly_window"]["forecast"]
    assert fc["basis_seconds"] == 12 * 3600 and fc["before_release"] is True


def test_single_sample_has_no_forecast(env):
    acc = env(minutes=60, native=30.0)
    assert "forecast" not in acc["native_window"]


def test_idle_consumption_forecast_never_exhausts(env):
    env(minutes=0, native=10.0)
    fc = env(minutes=20, native=10.0)["native_window"]["forecast"]
    assert fc["exhausts_at"] is None and fc["seconds_until"] is None and fc["before_release"] is False


def test_decreasing_usage_discards_old_samples(env):
    env(minutes=0, native=50.0)
    acc = env(minutes=10, native=5.0)  # reset do consumo
    assert "forecast" not in acc["native_window"]


def test_cycle_reset_in_middle_discards_samples(env):
    env(minutes=0, native=80.0)
    new_release = T0 + timedelta(minutes=10) + timedelta(hours=5)
    acc = env(minutes=10, native=85.0, release_native=new_release)  # liberacao mudou: outro ciclo
    assert "forecast" not in acc["native_window"]


def test_release_jitter_keeps_cycle(env):
    env(minutes=0, native=10.0)
    jitter = env.state["release_native"] + timedelta(seconds=7)
    assert "forecast" in env(minutes=10, native=20.0, release_native=jitter)["native_window"]


def test_expired_window_discards_samples(env):
    env(minutes=0, native=10.0)
    # janela encerrada ha 1h e liberacao nova: amostra antiga e de outro ciclo
    acc = env(minutes=6 * 60, native=4.0, release_native=T0 + timedelta(hours=11))
    assert "forecast" not in acc["native_window"]


def test_clock_going_backwards_discards_future_samples(env):
    env(minutes=30, native=40.0)
    acc = env(minutes=10, native=45.0)  # amostra "do futuro" e descartada
    assert "forecast" not in acc["native_window"]


@pytest.mark.parametrize("garbage", [
    "not json", "[]", '{"series": []}', '{"series": {"claude:a:native": 5}}',
    '{"series": {"claude:a:native": {"release": "x", "samples": "oops"}}}',
    '{"series": {"claude:a:native": {"release": 1, "samples": [[null, "x"], [1], "z", [true, 1]]}}}',
])
def test_corrupted_samples_file_is_tolerated(env, garbage):
    env(minutes=0, native=10.0)
    env.samples.write_text(garbage)
    assert env(minutes=10, native=20.0)["native_window"]["alert_level"] in ("normal", "warning")
    assert json.loads(env.samples.read_text())["series"]  # regravado sao


def test_samples_file_is_private(env):
    env(minutes=0, native=10.0)
    assert stat.S_IMODE(os.stat(env.samples).st_mode) == 0o600


def test_no_forecast_when_stale_or_no_data(env, monkeypatch):
    env(minutes=0, native=10.0)
    monkeypatch.setattr(refresh, "apply_outcome", lambda entry, *a, **k: entry.update(stale=True) or entry)
    acc = env(minutes=10, native=20.0)
    for w in ("native_window", "weekly_window"):
        assert not {"pace", "forecast", "alert_level"} & acc[w].keys()


def test_stale_previous_values_are_not_carried_over(env, monkeypatch):
    env(minutes=0, native=10.0)
    assert "forecast" in env(minutes=10, native=20.0)["native_window"]
    # 429: o ciclo serve a janela anterior (com a previsao antiga) marcada obsoleta
    def serve_previous(entry, outcome, previous, *a, **k):
        entry.update(stale=True, native_window=previous["native_window"])
        return entry
    monkeypatch.setattr(refresh, "apply_outcome", serve_previous)
    acc = env(minutes=20, native=30.0)
    assert acc["stale"] and not {"pace", "forecast", "alert_level"} & acc["native_window"].keys()


def test_local_source_has_no_forecast_or_pace(env):
    env(minutes=0, native=10.0, source="local")
    acc = env(minutes=10, native=20.0, source="local")
    assert "forecast" not in acc["native_window"] and "pace" not in acc["native_window"]
    assert acc["native_window"]["alert_level"] is None  # modo ritmo sem ritmo => sem nivel


def test_unknown_usage_has_no_level(env):
    acc = env(minutes=10, native=None)
    assert "alert_level" not in acc["native_window"] and "forecast" not in acc["native_window"]


def test_threshold_mode_default_70_90(env):
    assert main(["--set-alert-config", "--alert-mode", "threshold", *env.base]) == 0
    assert env(minutes=60, native=69.0)["native_window"]["alert_level"] == "normal"
    assert env(minutes=60, native=70.0)["native_window"]["alert_level"] == "warning"
    assert env(minutes=60, native=90.0)["native_window"]["alert_level"] == "critical"


def test_threshold_mode_custom_values_and_local_source(env):
    assert main(["--set-alert-config", "--alert-mode", "threshold", "--alert-warning", "40", "--alert-critical", "50", *env.base]) == 0
    acc = env(minutes=60, native=45.0, source="local")
    assert acc["native_window"]["alert_level"] == "warning" and "forecast" not in acc["native_window"]


@pytest.mark.parametrize("args", [
    ["--alert-warning", "90", "--alert-critical", "70"], ["--alert-warning", "0"], ["--alert-critical", "101"],
    ["--alert-warning", "80", "--alert-critical", "80"], ["--alert-warning", "nan"], ["--alert-critical", "-5"],
    ["--alert-mode", "bogus"],
])
def test_invalid_alert_config_is_rejected(env, args, capsys):
    before = env.config_path.read_text()
    with pytest.raises(SystemExit) if "bogus" in args else _noop():
        rc = main(["--set-alert-config", *args, *env.base])
        assert rc == 1
    assert env.config_path.read_text() == before


def test_partial_alert_update_validates_against_current(env):
    assert main(["--set-alert-config", "--alert-warning", "95", *env.base]) == 1  # critico atual e 90


def test_invalid_stored_alerts_fall_back_to_default(env):
    cfg = json.loads(env.config_path.read_text())
    cfg["alerts"] = {"mode": "threshold", "warning": 95, "critical": 10}
    env.config_path.write_text(json.dumps(cfg))
    assert "pace" in env(minutes=60, native=30.0)["native_window"]  # padrao: modo ritmo


class _noop:
    def __enter__(self): pass
    def __exit__(self, *a): return False
