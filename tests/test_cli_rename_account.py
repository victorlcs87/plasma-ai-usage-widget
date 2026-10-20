"""Tests for CLI --rename-account functionality."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config, save_config


def test_cli_rename_account_success(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "work-1",
                        "label": "Claude Trabalho Antigo",
                        "name": "Claude Trabalho Antigo",
                        "source": "manual",
                        "credential_path": "/path/to/creds",
                    }
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    code = main([
        "--rename-account", "claude", "work-1",
        "--label", "Claude Trabalho Novo",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'Claude Trabalho Novo' renomeada com sucesso!" in captured.out
    assert captured.err == ""

    # Verify config updated
    loaded = load_config(config_path)
    acc = loaded["agents"]["claude"]["accounts"][0]
    assert acc["label"] == "Claude Trabalho Novo"
    assert acc["name"] == "Claude Trabalho Novo"
    assert acc["id"] == "work-1"
    assert acc["source"] == "manual"
    assert acc["credential_path"] == "/path/to/creds"

    # Verify 0600 permissions
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600


def test_cli_rename_account_validation_empty_label(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "work-1", "label": "Claude Trabalho"}
                ]
            }
        },
    }
    save_config(cfg, config_path)

    code = main([
        "--rename-account", "claude", "work-1",
        "--label", "   ",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "Rótulo/nome da conta não pode ser vazio" in captured.err

    # Config must remain unchanged
    loaded = load_config(config_path)
    assert loaded["agents"]["claude"]["accounts"][0]["label"] == "Claude Trabalho"


def test_cli_rename_account_missing_label(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {"version": 1, "agents": {"claude": {"accounts": [{"id": "acc-1", "label": "A"}]}}}
    save_config(cfg, config_path)

    code = main([
        "--rename-account", "claude", "acc-1",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "Parâmetro --label / --name é obrigatório" in captured.err


def test_cli_rename_account_non_existent(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {"version": 1, "agents": {"claude": {"accounts": [{"id": "acc-1", "label": "A"}]}}}
    save_config(cfg, config_path)

    code = main([
        "--rename-account", "claude", "non-existent-id",
        "--label", "Novo Nome",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "Conta 'non-existent-id' não encontrada no provedor 'claude'." in captured.err


def test_cli_rename_account_invalid_provider(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {"version": 1, "agents": {}}
    save_config(cfg, config_path)

    code = main([
        "--rename-account", "unknown_provider", "acc-1",
        "--label", "Novo Nome",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "Provedor inválido 'unknown_provider'" in captured.err


def test_cli_rename_account_with_status(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "acc-status",
                        "label": "Original Label",
                        "name": "Original Label",
                        "source": "manual",
                        "credential_path": "/nonexistent",
                    }
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    code = main([
        "--rename-account", "claude", "acc-status",
        "--label", "Updated Label Through CLI",
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'Updated Label Through CLI' renomeada com sucesso!" in captured.out

    # Status JSON emitted in stdout
    json_start = captured.out.find("{")
    assert json_start != -1
    status_obj = json.loads(captured.out[json_start:])
    assert "agents" in status_obj
    claude_accs = status_obj["agents"]["claude"]["accounts"]
    assert len(claude_accs) == 1
    assert claude_accs[0]["name"] == "Updated Label Through CLI"
    assert claude_accs[0]["id"] == "acc-status"


def test_cli_rename_account_preserves_id_and_other_fields(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "gemini": {
                "accounts": [
                    {
                        "id": "gemini-custom-id",
                        "label": "Gemini Velho",
                        "name": "Gemini Velho",
                        "source": "manual",
                        "credential_path": "/tmp/custom_creds.json",
                        "gemini_dir": "/tmp/gemini_dir",
                        "manual_invite_url": "https://aistudio.google.com/test",
                        "rate_limit_capacity": 500,
                    }
                ]
            },
            "claude": {"accounts": []},
            "codex": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    # Subprocess run
    cmd = [
        sys.executable,
        "-m",
        "ai_usage_collector.cli",
        "--rename-account", "gemini", "gemini-custom-id",
        "--name", "Gemini Super",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Conta 'Gemini Super' renomeada com sucesso!" in res.stdout

    loaded = load_config(config_path)
    acc = loaded["agents"]["gemini"]["accounts"][0]
    assert acc["id"] == "gemini-custom-id"
    assert acc["label"] == "Gemini Super"
    assert acc["name"] == "Gemini Super"
    assert acc["source"] == "manual"
    assert acc["credential_path"] == "/tmp/custom_creds.json"
    assert acc["gemini_dir"] == "/tmp/gemini_dir"
    assert acc["manual_invite_url"] == "https://aistudio.google.com/test"
    assert acc["rate_limit_capacity"] == 500
