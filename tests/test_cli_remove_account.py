"""Tests for CLI --remove-account functionality."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config, save_config


def run_cli(*args):
    cmd = [sys.executable, "-m", "ai_usage_collector.cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_cli_remove_account_success(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "default", "name": "Claude Padrão"},
                    {"id": "work", "name": "Claude Trabalho"},
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    # Pre-populate status cache
    cache = {
        "version": 1,
        "last_updated": "2026-10-20T10:00:00Z",
        "status": "ok",
        "agents": {
            "claude": {
                "name": "Claude",
                "status": "ok",
                "accounts": [
                    {"id": "default", "label": "Claude Padrão", "health": {"status": "valid"}},
                    {"id": "work", "label": "Claude Trabalho", "health": {"status": "valid"}},
                ],
            },
            "codex": {"name": "Codex", "status": "ok", "accounts": []},
            "gemini": {"name": "Gemini", "status": "ok", "accounts": []},
        },
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    # Run CLI
    code = main([
        "--remove-account", "claude", "work",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'work' removida com sucesso do provedor 'claude'." in captured.out
    assert captured.err == ""

    # Verify config
    loaded_cfg = load_config(config_path)
    claude_accs = loaded_cfg["agents"]["claude"]["accounts"]
    assert len(claude_accs) == 1
    assert claude_accs[0]["id"] == "default"

    # Verify cache
    with open(cache_path, "r", encoding="utf-8") as f:
        loaded_cache = json.load(f)
    cache_claude_accs = loaded_cache["agents"]["claude"]["accounts"]
    assert len(cache_claude_accs) == 1
    assert cache_claude_accs[0]["id"] == "default"


def test_cli_remove_account_non_existent(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "default", "name": "Claude Padrão"}
                ]
            }
        },
    }
    save_config(cfg, config_path)

    code = main([
        "--remove-account", "claude", "non_existent_id",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "Conta 'non_existent_id' não encontrada no provedor 'claude'." in captured.err

    # Config remains untouched
    loaded_cfg = load_config(config_path)
    assert len(loaded_cfg["agents"]["claude"]["accounts"]) == 1


def test_cli_remove_account_invalid_provider(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {"version": 1, "agents": {}}
    save_config(cfg, config_path)

    code = main([
        "--remove-account", "openai_chatgpt", "acc1",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "Provedor inválido 'openai_chatgpt'" in captured.err


def test_cli_remove_account_preserves_other_accounts_and_0600(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "personal", "name": "Claude Pessoal"},
                    {"id": "work", "name": "Claude Trabalho"},
                ]
            },
            "codex": {
                "accounts": [
                    {"id": "default", "name": "Codex Padrão"}
                ]
            },
            "gemini": {
                "accounts": [
                    {"id": "default", "name": "Gemini Padrão"}
                ]
            },
        },
    }
    save_config(cfg, config_path)

    res = run_cli(
        "--remove-account", "Claude", "work",  # Case-insensitive provider
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    )
    assert res.returncode == 0
    assert "removida com sucesso" in res.stdout

    # Permissions
    config_mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert config_mode == 0o600, f"Expected 0600, got {oct(config_mode)}"

    # Check preserved accounts
    loaded_cfg = load_config(config_path)
    assert len(loaded_cfg["agents"]["claude"]["accounts"]) == 1
    assert loaded_cfg["agents"]["claude"]["accounts"][0]["id"] == "personal"
    assert len(loaded_cfg["agents"]["codex"]["accounts"]) == 1
    assert len(loaded_cfg["agents"]["gemini"]["accounts"]) == 1


def test_cli_remove_account_without_status_cache(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "gemini": {
                "accounts": [
                    {"id": "edu", "name": "Gemini Edu"},
                ]
            }
        },
    }
    save_config(cfg, config_path)
    assert not cache_path.exists()

    res = run_cli(
        "--remove-account", "gemini", "edu",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    )
    assert res.returncode == 0
    assert "removida com sucesso" in res.stdout
    assert not cache_path.exists()

    loaded_cfg = load_config(config_path)
    assert len(loaded_cfg["agents"]["gemini"]["accounts"]) == 0


def test_cli_remove_account_with_status_flag(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "codex": {
                "accounts": [
                    {"id": "acc-1", "name": "Codex 1"},
                    {"id": "acc-2", "name": "Codex 2"},
                ]
            }
        },
    }
    save_config(cfg, config_path)

    cache = {
        "version": 1,
        "last_updated": "2026-10-20T10:00:00Z",
        "status": "ok",
        "agents": {
            "claude": {"name": "Claude", "status": "ok", "accounts": []},
            "codex": {
                "name": "Codex",
                "status": "ok",
                "accounts": [
                    {"id": "acc-1", "name": "Codex 1"},
                    {"id": "acc-2", "name": "Codex 2"},
                ],
            },
            "gemini": {"name": "Gemini", "status": "ok", "accounts": []},
        },
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    res = run_cli(
        "--remove-account", "codex", "acc-2",
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    )
    assert res.returncode == 0
    assert "removida com sucesso" in res.stdout

    # Contains JSON output
    json_start = res.stdout.find("{")
    assert json_start != -1
    parsed_json = json.loads(res.stdout[json_start:])
    assert len(parsed_json["agents"]["codex"]["accounts"]) == 1
    assert parsed_json["agents"]["codex"]["accounts"][0]["id"] == "acc-1"


def test_cli_remove_account_entrypoint(tmp_path):
    venv_bin = os.path.join(os.path.dirname(sys.executable), "ai-usage-collector")
    if not os.path.exists(venv_bin):
        return

    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "bin-test", "name": "Binary Test"}
                ]
            }
        },
    }
    save_config(cfg, config_path)

    # 1. Success case
    cmd = [
        venv_bin,
        "--remove-account", "claude", "bin-test",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "removida com sucesso" in res.stdout

    # 2. Not found case
    cmd_not_found = [
        venv_bin,
        "--remove-account", "claude", "bin-test",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ]
    res_err = subprocess.run(cmd_not_found, capture_output=True, text=True)
    assert res_err.returncode == 1
    assert "não encontrada" in res_err.stderr
