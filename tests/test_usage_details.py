"""Usage details: Claude per-model/per-project tokens and extra usage; Codex credits and current model."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

from ai_usage_collector.contract import (
    build_agent_account_status,
    build_empty_status_contract,
    validate_status_contract,
)
from ai_usage_collector.extractors.claude import (
    extract_claude_status,
    parse_extra_usage,
    scan_project_token_breakdown,
)
from ai_usage_collector.extractors.codex import (
    extract_codex_status,
    parse_codex_credits,
    read_codex_current_model,
)

NOW = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)


def _entry(ts: str, cwd: str, model: str, inp: int, out: int) -> str:
    return json.dumps({
        "timestamp": ts,
        "cwd": cwd,
        "message": {"model": model, "usage": {"input_tokens": inp, "output_tokens": out}},
    })


def _write_claude_projects(tmp_path):
    repo = tmp_path / "repos" / "app"
    (repo / ".git").mkdir(parents=True)
    worktree = repo / ".claude" / "worktrees" / "wt1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {repo}/.git/worktrees/wt1\n")
    other = tmp_path / "repos" / "lib" / "src"
    (other.parent / ".git").mkdir(parents=True)
    other.mkdir()

    claude_dir = tmp_path / ".claude"
    projects = claude_dir / "projects"
    for slug, lines in {
        "-repos-app": [
            _entry("2026-10-20T10:00:00Z", str(repo), "claude-opus", 100, 50),
            _entry("2026-10-01T10:00:00Z", str(repo), "claude-opus", 999, 999),  # before reset
        ],
        "-repos-app-wt1": [_entry("2026-10-20T11:00:00Z", str(worktree), "claude-sonnet", 10, 5)],
        "-repos-lib-src": [_entry("2026-10-19T11:00:00Z", str(other), "claude-sonnet", 300, 0)],
    }.items():
        d = projects / slug
        d.mkdir(parents=True)
        (d / "s.jsonl").write_text("\n".join(lines) + "\n")
    return claude_dir


def test_breakdown_groups_by_model_and_git_repo(tmp_path):
    claude_dir = _write_claude_projects(tmp_path)
    since = datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()

    by_model, by_project = scan_project_token_breakdown(claude_dir / "projects", since)

    assert by_model == {"claude-opus": 150, "claude-sonnet": 315}
    assert by_project == {"app": 165, "lib": 300}  # worktree folded into main repo


def test_breakdown_missing_dir_is_empty(tmp_path):
    assert scan_project_token_breakdown(tmp_path / "nope", 0) == ({}, {})


def test_parse_extra_usage():
    assert parse_extra_usage(None) is None
    assert parse_extra_usage({}) is None
    assert parse_extra_usage({"extra_usage": {"is_enabled": False, "used_credits": 10}}) is None
    assert parse_extra_usage({"extra_usage": {"is_enabled": True, "used_credits": None}}) is None
    assert parse_extra_usage(
        {"extra_usage": {"is_enabled": True, "used_credits": 1234, "monthly_limit": 5000}}
    ) == {"spent": 12.34, "monthly_limit": 50.0, "currency": "USD"}
    # Limit absent: key omitted, not empty
    assert parse_extra_usage({"extra_usage": {"is_enabled": True, "used_credits": 50}}) == {
        "spent": 0.5,
        "currency": "USD",
    }


def test_claude_status_usage_details_since_last_weekly_reset(tmp_path):
    claude_dir = _write_claude_projects(tmp_path)
    (claude_dir / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "x"}}))
    api = {
        "five_hour": {"utilization": 1.0},
        # Next reset 2026-10-26T11:30 -> last reset 2026-10-19T11:30 (excludes the lib entry at 11:00)
        "seven_day": {"utilization": 2.0, "resets_at": "2026-10-26T11:30:00Z"},
        "extra_usage": {"is_enabled": True, "used_credits": 200, "monthly_limit": 1000},
    }
    with patch("ai_usage_collector.extractors.claude.fetch_claude_usage_api", return_value=api):
        res = extract_claude_status(
            {"id": "c", "claude_dir": str(claude_dir)},
            initial_health={"status": "valid", "metadata": {}},
            now=NOW,
        )

    d = res["usage_details"]
    assert d["since"] == "2026-10-19T11:30:00+00:00"
    assert d["tokens_by_model"] == [{"model": "claude-opus", "tokens": 150}, {"model": "claude-sonnet", "tokens": 15}]
    assert d["tokens_by_project"] == [{"project": "app", "tokens": 165}]
    assert d["extra_usage"] == {"spent": 2.0, "monthly_limit": 10.0, "currency": "USD"}


def test_claude_status_without_details_omits_key(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    with patch("ai_usage_collector.extractors.claude.fetch_claude_usage_api", return_value=None):
        res = extract_claude_status({"id": "c", "claude_dir": str(claude_dir)}, now=NOW)
    assert "usage_details" not in res


def test_parse_codex_credits():
    assert parse_codex_credits(None) is None
    assert parse_codex_credits({"credits": None}) is None
    assert parse_codex_credits({"credits": {"has_credits": False, "unlimited": False, "balance": "0"}}) is None
    assert parse_codex_credits({"credits": {"has_credits": True, "balance": "bad"}}) is None
    assert parse_codex_credits({"credits": {"has_credits": True, "unlimited": False, "balance": "12.5"}}) == {
        "unlimited": False,
        "balance": 12.5,
    }
    assert parse_codex_credits({"credits": {"has_credits": True, "unlimited": True}}) == {"unlimited": True}


def test_codex_current_model_from_latest_rollout_then_config(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    assert read_codex_current_model(codex_dir) is None

    (codex_dir / "config.toml").write_text('approval = "x"\nmodel = "gpt-5"\n[profiles.p]\nmodel = "o3"\n')
    assert read_codex_current_model(codex_dir) == "gpt-5"

    day = codex_dir / "sessions" / "2026" / "10" / "20"
    day.mkdir(parents=True)
    old = day / "rollout-old.jsonl"
    old.write_text(json.dumps({"type": "turn_context", "payload": {"model": "gpt-old"}}) + "\n")
    os.utime(old, (1, 1))
    new = day / "rollout-new.jsonl"
    new.write_text(
        "\n".join([
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-5-codex"}}),
            "not json turn_context",
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.1-codex"}}),
        ]) + "\n"
    )
    assert read_codex_current_model(codex_dir) == "gpt-5.1-codex"


def test_codex_status_usage_details(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}))
    (codex_dir / "config.toml").write_text('model = "gpt-5"\n')
    api = {
        "rate_limit": {"primary_window": {"used_percent": 10}, "secondary_window": {"used_percent": 20}},
        "credits": {"has_credits": True, "unlimited": False, "balance": "3"},
    }
    with patch("ai_usage_collector.extractors.codex.fetch_codex_usage_api", return_value=api):
        res = extract_codex_status(
            {"id": "x", "codex_dir": str(codex_dir)},
            initial_health={"status": "valid", "metadata": {}},
            now=NOW,
        )
    assert res["usage_details"] == {"credits": {"unlimited": False, "balance": 3.0}, "current_model": "gpt-5"}


def test_codex_status_without_details_omits_key(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    res = extract_codex_status({"id": "x", "codex_dir": str(codex_dir)}, now=NOW)
    assert "usage_details" not in res


def test_contract_usage_details_optional_and_versioned():
    payload = build_empty_status_contract()
    assert payload["version"] == 5
    plain = build_agent_account_status("codex", "a", "A", "auto", {"status": "valid"})
    assert "usage_details" not in plain
    rich = build_agent_account_status(
        "codex", "b", "B", "auto", {"status": "valid"}, usage_details={"current_model": "gpt-5"}
    )
    assert rich["usage_details"] == {"current_model": "gpt-5"}
    payload["agents"]["codex"]["accounts"] = [plain, rich]
    assert validate_status_contract(payload) is True
    payload["version"] = 1  # older payloads remain valid
    assert validate_status_contract(payload) is True


def test_invalid_utf8_does_not_break_extraction(tmp_path):
    claude_dir = _write_claude_projects(tmp_path)
    (claude_dir / "projects" / "-repos-app" / "bad.jsonl").write_bytes(b"\xff\xfe\"usage\"\n")
    by_model, _ = scan_project_token_breakdown(claude_dir / "projects", 0)
    assert by_model["claude-opus"] == 150 + 1998

    codex_dir = tmp_path / ".codex"
    day = codex_dir / "sessions" / "2026" / "10" / "20"
    day.mkdir(parents=True)
    (day / "rollout-x.jsonl").write_bytes(b"\xff turn_context\n")
    (codex_dir / "config.toml").write_bytes(b'\xff\nmodel = "gpt-5"\n')
    assert read_codex_current_model(codex_dir) == "gpt-5"
