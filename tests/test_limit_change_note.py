"""Nota de mudanca de limites: deteccao contra o ultimo cache e validade de 3 dias."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from ai_usage_collector import collector
from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config
from ai_usage_collector.contract import validate_status_contract

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _native(seconds=18000, release=T0 + timedelta(hours=2), source="api"):
    return {"window_seconds": seconds, "release_time": release.isoformat(), "seconds_remaining": 7200, "source": source}


def _weekly(seconds=604800, source="api"):
    return {"window_seconds": seconds, "cycle_reset_time": (T0 + timedelta(days=3)).isoformat(), "source": source}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = {"version": 1, "agents": {"claude": {"accounts": [{"id": "a", "label": "A", "source": "manual"}]},
                                    "codex": {"accounts": []}, "gemini": {"accounts": []}}}
    config_path = tmp_path / "config.json"
    save_config(cfg, config_path)
    state = {"native": _native(), "weekly": _weekly(), "health": {"status": "valid"}}
    monkeypatch.setattr(collector, "extract_claude_status", lambda acc, initial_health=None, now=None: {
        "health": state["health"], "native_window": state["native"], "weekly_window": state["weekly"]})
    monkeypatch.setattr(collector, "apply_token_history", lambda *a, **k: None)
    cache_path = tmp_path / "cache" / "status.json"
    clock = {"now": T0}

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(collector, "datetime", FakeDatetime)

    def run(now=T0, **changes):
        state.update(changes)
        clock["now"] = now
        assert main(["--refresh", "--config-path", str(config_path), "--cache-path", str(cache_path)]) == 0
        return json.loads(cache_path.read_text())["agents"]["claude"]["accounts"][0]

    run.cache_path = cache_path
    run()
    return run


def _kinds(acc):
    return sorted((c["window"], c["kind"]) for c in acc.get("limit_changes", []))


def test_no_change_no_note(env):
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=5))


@pytest.mark.parametrize("changes, expected", [
    ({"native": _native(source="api_missing")}, [("native", "removed")]),
    ({"weekly": _weekly(source="api_missing")}, [("weekly", "removed")]),
    ({"native": _native(10800)}, [("native", "duration")]),
    ({"native": _native(release=T0 + timedelta(minutes=30))}, [("native", "early_reset")]),
])
def test_each_change_kind_is_detected(env, changes, expected):
    assert _kinds(env(now=T0 + timedelta(minutes=5), **changes)) == expected


def test_window_added(env):
    env(now=T0 + timedelta(minutes=1), weekly=_weekly(source="api_missing"))
    assert ("weekly", "added") in _kinds(env(now=T0 + timedelta(minutes=2), weekly=_weekly()))


def test_removed_needs_api_answer_without_bucket(env):
    # Falha da API (leitura local) nao e janela removida (M2)
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=5), weekly=_weekly(source="local"))


@pytest.mark.parametrize("fallback", [
    {"native": _native(release=T0 + timedelta(minutes=30), source="local")},  # A1: reset local difere da API
    {"native": _native(10800, source="local")},  # A2: duracao padrao assumida
    {"weekly": _weekly(86400, source="local")},
])
def test_local_fallback_readings_never_count(env, fallback):
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=5), **fallback)


def test_return_from_fallback_to_api_is_not_a_change(env):
    env(now=T0 + timedelta(minutes=5), native=_native(release=T0 + timedelta(minutes=30), source="local"))
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=10))


def test_note_expires_after_three_days(env):
    t = T0 + timedelta(minutes=5)
    acc = env(now=t, native=_native(10800))
    assert acc["limit_changes"][0]["expires_at"] == (t + timedelta(days=3)).isoformat()
    assert _kinds(env(now=t + timedelta(days=3) - timedelta(seconds=1))) == [("native", "duration")]
    assert "limit_changes" not in env(now=t + timedelta(days=3))


def test_invalid_health_never_counts_as_change(env):
    acc = env(now=T0 + timedelta(minutes=5), health={"status": "session_expired"},
              native=_native(source="api_missing"), weekly=_weekly(source="api_missing"))
    assert "limit_changes" not in acc


def test_clock_jitter_is_not_early_reset(env):
    near = T0 + timedelta(hours=2) - timedelta(seconds=30)  # reset informado oscila < 1 min
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=5), native=_native(release=near))
    # relogio andando para tras tambem nao inventa mudanca
    assert "limit_changes" not in env(now=T0 - timedelta(hours=1), native=_native())


@pytest.mark.parametrize("garbage", [
    "not json{", "[]", '{"agents": null}', '{"agents": {"claude": null}}', '{"agents": {"claude": {"accounts": "x"}}}',
    '{"agents": {"claude": {"accounts": [1, null, {"id": "a", "health": null}]}}}',
    '{"agents": {"claude": {"accounts": [{"id": "a", "health": {"status": "valid"}, "native_window": null}]}}}',
    '{"agents": {"claude": {"accounts": [{"id": "a", "health": {"status": "valid"}, "native_window": "x"}]}}}',
    '{"agents": {"claude": {"accounts": [{"id": "a", "health": "x", "limit_changes": [1]}]}}}',
])
def test_corrupt_previous_cache_never_breaks_status(env, garbage):
    env.cache_path.write_text(garbage)
    acc = env(now=T0 + timedelta(minutes=5))
    assert "limit_changes" not in acc


def test_corrupt_account_does_not_drop_other_notes(env):
    env(now=T0 + timedelta(minutes=1), native=_native(10800))
    cache = json.loads(env.cache_path.read_text())
    cache["agents"]["codex"]["accounts"] = [{"id": "z", "health": 5, "native_window": "x", "limit_changes": [1]}]
    env.cache_path.write_text(json.dumps(cache))
    assert _kinds(env(now=T0 + timedelta(minutes=2), native=_native(10800))) == [("native", "duration")]


def test_missing_cache_is_fine(env):
    env.cache_path.unlink()
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=5))


def test_contract_validates_limit_changes(env):
    env(now=T0 + timedelta(minutes=5), native=_native(10800))
    data = json.loads(env.cache_path.read_text())
    assert validate_status_contract(data) is True
    data["agents"]["claude"]["accounts"][0]["limit_changes"] = [1]
    assert validate_status_contract(data) is False
    data["agents"]["claude"]["accounts"][0]["limit_changes"] = "x"
    assert validate_status_contract(data) is False
