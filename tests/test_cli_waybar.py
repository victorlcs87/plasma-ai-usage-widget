"""Saida --waybar pela CLI: cache falso, sem rede e sem coleta."""

import json
import unicodedata
import subprocess
import sys

import pytest

from ai_usage_collector import collector


def acc(label, active, native=None, weekly=None, **extra):
    def win(pct, lvl):
        w = {"usage_percentage": pct}
        if lvl:
            w["alert_level"] = lvl
        return w
    return {"id": label, "label": label, "provider": "x", "isActive": active,
            "native_window": win(*native) if native else {}, "weekly_window": win(*weekly) if weekly else {}, **extra}


def run(tmp_path, claude=(), codex=(), raw=None):
    cache = tmp_path / "status.json"
    if raw is not None:
        cache.write_text(raw)
    elif raw is None and (claude or codex):
        cache.write_text(json.dumps({"version": 5, "agents": {
            "claude": {"name": "Claude", "accounts": list(claude)},
            "codex": {"name": "Codex", "accounts": list(codex)}, "gemini": {"name": "Gemini", "accounts": []}}}))
    res = subprocess.run([sys.executable, "-m", "ai_usage_collector.cli", "--waybar", "--cache-path", str(cache),
                          "--config-path", str(tmp_path / "config.json")], capture_output=True, text=True)
    assert res.returncode == 0
    assert res.stdout.count("\n") == 1 and res.stdout.endswith("\n")
    assert not (tmp_path / "config.json").exists()  # nao coletou
    return json.loads(res.stdout)


def test_worst_level_among_active_accounts(tmp_path):
    out = run(tmp_path, claude=[acc("A", True, (40, "normal"), (60, "warning"))],
              codex=[acc("B", True, (95, "critical"))])
    assert out["class"] == out["alt"] == "critical"
    assert out["text"] == "Claude 60% · Codex 95%"
    assert out["percentage"] == 95
    assert "\n  janela: 40% (normal)" in out["tooltip"]


def test_inactive_account_does_not_count(tmp_path):
    out = run(tmp_path, claude=[acc("A", True, (10, "normal")), acc("Z", False, (99, "critical"))])
    assert out["class"] == "normal"
    assert "Z" not in out["tooltip"]


@pytest.mark.parametrize("extra", [{"stale": True}, {"fetch_error": {"kind": "rate_limited"}}])
def test_stale_or_429_has_no_invented_level(tmp_path, extra):
    out = run(tmp_path, claude=[acc("A", True, (50, None), **extra)])
    assert out["class"] == "stale"
    assert out["text"] == "Claude —"
    assert "percentage" not in out


def test_no_level_is_unknown(tmp_path):
    assert run(tmp_path, claude=[acc("A", True, (0, None))])["class"] == "unknown"  # leitura local
    (tmp_path / "x").mkdir()
    assert run(tmp_path / "x", claude=[acc("A", False, (9, "critical"))])["class"] == "unknown"  # sem conta ativa


def test_no_cache(tmp_path):
    out = run(tmp_path)
    assert out["text"] == "—" and out["class"] == "unknown"


@pytest.mark.parametrize("raw", ["{nao e json", "[]", '{"agents": 3}', '{"agents": {"claude": {"accounts": [1]}}}'])
def test_corrupted_cache_falls_back(tmp_path, raw):
    out = run(tmp_path, raw=raw)
    assert out["text"] == "—" and out["class"] == "unknown"


def test_untrusted_label_is_escaped_single_line(tmp_path):
    out = run(tmp_path, claude=[acc("<b>&\nx", True, (10, "normal"))])
    assert "<b>" not in out["tooltip"]
    assert "&lt;b&gt;&amp; x" in out["tooltip"]
    assert out["tooltip"].count("\n") == 1


def test_waybar_never_collects(tmp_path, monkeypatch, capsys):
    from ai_usage_collector.cli import main
    monkeypatch.setattr(collector, "collect_and_save", lambda *a, **k: pytest.fail("coletou"))
    assert main(["--waybar", "--cache-path", str(tmp_path / "nope.json"), "--config-path", str(tmp_path / "c.json")]) == 0
    assert json.loads(capsys.readouterr().out)["text"] == "—"


def raw_cache(tmp_path, claude_acc, name="Claude"):
    cache = tmp_path / "s.json"
    cache.write_text(json.dumps({"agents": {"claude": {"name": name, "accounts": claude_acc}}}))
    return run(tmp_path, raw=cache.read_text())


def test_lone_surrogate_label(tmp_path):
    out = raw_cache(tmp_path, [acc("\ud800x", True, (10, "normal"))])
    assert out["class"] == "normal" and "x" in out["tooltip"]


def test_control_and_bidi_stripped(tmp_path):
    out = raw_cache(tmp_path, [acc("a\x00\x1b‮b⁦c\x85d", True, (10, "normal"))])
    assert "a" in out["tooltip"] and not any(unicodedata.category(c) == "Cf" or ord(c) < 32 and c != "\n" for c in out["tooltip"])
    assert "abc d" in out["tooltip"]


def test_nan_inf_ignored_only_bad_value(tmp_path):
    raw = json.dumps({"agents": {"claude": {"name": "C", "accounts": [
        acc("A", True, (50, "warning"), (0, None)), acc("B", True)]}}})
    raw = raw.replace('"usage_percentage": 0', '"usage_percentage": NaN')
    out = run(tmp_path, raw=raw)
    assert out["class"] == "warning" and out["percentage"] == 50
    out = run(tmp_path / "i" if (tmp_path / "i").mkdir() else tmp_path, raw=raw.replace("NaN", "Infinity"))
    assert out["class"] == "warning" and out["percentage"] == 50


def test_absurd_percentage_clamped(tmp_path):
    out = raw_cache(tmp_path, [acc("A", True, (1e300, "critical"), (-5, "normal"))])
    assert out["text"] == "Claude 100%" and "-5" not in out["tooltip"] and "janela: 100%" in out["tooltip"]


def test_bad_cache_path_tilde_user(tmp_path):
    res = subprocess.run([sys.executable, "-m", "ai_usage_collector.cli", "--waybar", "--cache-path", "~nouser_zz/x"],
                         capture_output=True, text=True)
    assert res.returncode == 0 and json.loads(res.stdout)["class"] == "unknown"


def test_non_str_agent_name_uses_provider(tmp_path):
    out = raw_cache(tmp_path, [acc("A", True, (10, "normal"))], name=["x"])
    assert out["text"] == "claude 10%"


def test_tooltip_line_limit(tmp_path):
    out = raw_cache(tmp_path, [acc(f"L{i}", True, (10, "normal")) for i in range(30)])
    assert len(out["tooltip"].split("\n")) == 21


def test_two_active_accounts_same_agent_keep_agent_name(tmp_path):
    out = raw_cache(tmp_path, [acc("A", True, (10, "normal")), acc("B", True, (20, "normal"))])
    assert out["text"] == "Claude 10% · Claude 20%"
