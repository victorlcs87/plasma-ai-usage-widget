"""Nota de mudanca de limites: deteccao contra o ultimo cache e validade de 3 dias."""

from datetime import datetime, timedelta, timezone

import json

import pytest

from ai_usage_collector import collector
from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _native(seconds=18000, release=T0 + timedelta(hours=2)):
    if seconds is None:
        return {"window_seconds": None, "release_time": None}
    return {"window_seconds": seconds, "release_time": release.isoformat(), "seconds_remaining": 7200}


def _weekly(seconds=604800):
    if seconds is None:
        return {"window_seconds": None, "cycle_reset_time": None}
    return {"window_seconds": seconds, "cycle_reset_time": (T0 + timedelta(days=3)).isoformat()}


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

    run()
    return run


def _kinds(acc):
    return sorted((c["window"], c["kind"]) for c in acc.get("limit_changes", []))


def test_no_change_no_note(env):
    assert "limit_changes" not in env(now=T0 + timedelta(minutes=5))


@pytest.mark.parametrize("changes, expected", [
    ({"native": _native(None)}, [("native", "removed")]),
    ({"weekly": _weekly(None)}, [("weekly", "removed")]),
    ({"native": _native(10800)}, [("native", "duration")]),
    ({"native": _native(release=T0 + timedelta(minutes=30))}, [("native", "early_reset")]),
])
def test_each_change_kind_is_detected(env, changes, expected):
    acc = env(now=T0 + timedelta(minutes=5), **changes)
    assert _kinds(acc) == expected


def test_window_added(env):
    env(now=T0 + timedelta(minutes=1), weekly=_weekly(None))
    acc = env(now=T0 + timedelta(minutes=2), weekly=_weekly())
    assert ("weekly", "added") in _kinds(acc)


def test_note_expires_after_three_days(env):
    t = T0 + timedelta(minutes=5)
    acc = env(now=t, native=_native(10800))
    assert acc["limit_changes"][0]["expires_at"] == (t + timedelta(days=3)).isoformat()
    assert _kinds(env(now=t + timedelta(days=3) - timedelta(seconds=1))) == [("native", "duration")]
    assert "limit_changes" not in env(now=t + timedelta(days=3))


def test_invalid_health_never_counts_as_change(env):
    acc = env(now=T0 + timedelta(minutes=5), health={"status": "session_expired"}, native=_native(None), weekly=_weekly(None))
    assert "limit_changes" not in acc


