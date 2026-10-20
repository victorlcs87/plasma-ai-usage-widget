"""Tests for multi-account management and account removal in configuration and collector."""

from datetime import datetime, timezone
import json
import os
import stat
from pathlib import Path
import pytest

from ai_usage_collector.collector import (
    collect_and_save,
    load_status_cache,
    remove_account,
    remove_account_from_cache,
)
from ai_usage_collector.config import (
    SUPPORTED_PROVIDERS,
    add_account,
    add_account_to_config,
    load_config,
    remove_account_from_config,
    save_config,
)
from ai_usage_collector.contract import validate_status_contract


def test_add_and_configure_multiple_accounts(tmp_path):
    config_path = tmp_path / "config.json"

    # Start with empty config
    cfg = {"version": 1, "agents": {}}
    save_config(cfg, config_path)

    # 1. Add secondary account to claude
    acc_claude_1 = {
        "id": "personal",
        "name": "Claude Pessoal",
        "source": "manual",
        "manual_invite_url": "https://claude.ai/invite/personal",
        "manual_invite_count": 2,
    }
    updated_cfg = add_account("claude", acc_claude_1, config_path=config_path)

    claude_accounts = updated_cfg["agents"]["claude"]["accounts"]
    assert len(claude_accounts) == 1
    assert claude_accounts[0]["id"] == "personal"
    assert claude_accounts[0]["name"] == "Claude Pessoal"
    assert claude_accounts[0]["manual_invite_url"] == "https://claude.ai/invite/personal"
    assert claude_accounts[0]["manual_invite_count"] == 2

    # 2. Add second account to claude
    acc_claude_2 = {
        "id": "work",
        "name": "Claude Trabalho",
        "source": "manual",
        "manual_invite_url": "https://claude.ai/invite/work",
        "manual_invite_count": 5,
    }
    updated_cfg = add_account("claude", acc_claude_2, config_path=config_path)
    assert len(updated_cfg["agents"]["claude"]["accounts"]) == 2

    # 3. Update existing account
    acc_claude_2_updated = {
        "id": "work",
        "name": "Claude Corporativo",
        "manual_invite_count": 10,
    }
    updated_cfg = add_account("claude", acc_claude_2_updated, config_path=config_path)
    assert len(updated_cfg["agents"]["claude"]["accounts"]) == 2
    work_acc = next(a for a in updated_cfg["agents"]["claude"]["accounts"] if a["id"] == "work")
    assert work_acc["name"] == "Claude Corporativo"
    assert work_acc["manual_invite_count"] == 10
    # source and manual_invite_url preserved from original
    assert work_acc["source"] == "manual"
    assert work_acc["manual_invite_url"] == "https://claude.ai/invite/work"

    # 4. Error on unsupported provider
    with pytest.raises(ValueError, match="não suportado"):
        add_account_to_config(updated_cfg, "unsupported_ai", {"id": "test"})

    # 5. Error on missing id
    with pytest.raises(ValueError, match="identificador 'id'"):
        add_account_to_config(updated_cfg, "claude", {"name": "No ID"})


def test_collector_processes_all_multiple_accounts_for_each_agent(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # Setup directories for multi-account fixtures
    claude_dir1 = tmp_path / "claude_personal"
    claude_dir1.mkdir()
    (claude_dir1 / ".credentials.json").write_text(json.dumps({
        "claudeAiOauth": {
            "accessToken": "token-claude-personal",
            "subscriptionType": "free",
        }
    }))

    claude_dir2 = tmp_path / "claude_work"
    claude_dir2.mkdir()
    (claude_dir2 / ".credentials.json").write_text(json.dumps({
        "claudeAiOauth": {
            "accessToken": "token-claude-work",
            "subscriptionType": "max",
        }
    }))

    codex_dir1 = tmp_path / "codex_main"
    codex_dir1.mkdir()
    (codex_dir1 / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": "token-codex-1"},
    }))

    codex_dir2 = tmp_path / "codex_team"
    codex_dir2.mkdir()
    (codex_dir2 / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": "token-codex-2"},
    }))

    gemini_dir1 = tmp_path / "gemini_dev"
    gemini_dir1.mkdir()
    (gemini_dir1 / "oauth_creds.json").write_text(json.dumps({
        "access_token": "token-gemini-1",
        "refresh_token": "ref-1",
    }))

    config_data = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "personal",
                        "name": "Claude Pessoal",
                        "source": "auto",
                        "claude_dir": str(claude_dir1),
                        "manual_invite_url": "https://claude.ai/invite/c1",
                        "manual_invite_count": 3,
                    },
                    {
                        "id": "work",
                        "name": "Claude Trabalho",
                        "source": "auto",
                        "claude_dir": str(claude_dir2),
                        "manual_invite_url": "https://claude.ai/invite/c2",
                        "manual_invite_count": 7,
                    },
                ]
            },
            "codex": {
                "accounts": [
                    {
                        "id": "codex-1",
                        "name": "Codex Pessoal",
                        "source": "auto",
                        "codex_dir": str(codex_dir1),
                        "manual_invite_url": "https://chatgpt.com/invite/co1",
                    },
                    {
                        "id": "codex-2",
                        "name": "Codex Equipe",
                        "source": "auto",
                        "codex_dir": str(codex_dir2),
                        "manual_invite_url": "https://chatgpt.com/invite/co2",
                    },
                ]
            },
            "gemini": {
                "accounts": [
                    {
                        "id": "gemini-1",
                        "name": "Gemini Dev",
                        "source": "auto",
                        "gemini_dir": str(gemini_dir1),
                        "manual_invite_url": "https://aistudio.google.com/invite/g1",
                        "manual_invite_count": 4,
                    }
                ]
            },
        },
    }
    save_config(config_data, config_path)

    # Execute collector
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    status = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)

    assert validate_status_contract(status) is True

    # Check Claude accounts
    claude_res = status["agents"]["claude"]
    assert claude_res["status"] == "ok"
    assert len(claude_res["accounts"]) == 2
    assert claude_res["accounts"][0]["id"] == "personal"
    assert claude_res["accounts"][0]["name"] == "Claude Pessoal"
    assert claude_res["accounts"][0]["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/c1"
    assert claude_res["accounts"][0]["free_trial_invites"]["available_count"] == 3
    assert claude_res["accounts"][1]["id"] == "work"
    assert claude_res["accounts"][1]["name"] == "Claude Trabalho"
    assert claude_res["accounts"][1]["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/c2"
    assert claude_res["accounts"][1]["free_trial_invites"]["available_count"] == 7

    # Check Codex accounts
    codex_res = status["agents"]["codex"]
    assert codex_res["status"] == "ok"
    assert len(codex_res["accounts"]) == 2
    assert codex_res["accounts"][0]["id"] == "codex-1"
    assert codex_res["accounts"][0]["name"] == "Codex Pessoal"
    assert codex_res["accounts"][1]["id"] == "codex-2"
    assert codex_res["accounts"][1]["name"] == "Codex Equipe"

    # Check Gemini accounts
    gemini_res = status["agents"]["gemini"]
    assert gemini_res["status"] == "ok"
    assert len(gemini_res["accounts"]) == 1
    assert gemini_res["accounts"][0]["id"] == "gemini-1"
    assert gemini_res["accounts"][0]["name"] == "Gemini Dev"
    assert gemini_res["accounts"][0]["free_trial_invites"]["available_count"] == 4


def test_remove_account_from_config_success(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "default", "name": "Claude Padrão"},
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

    success, msg = remove_account("claude", "work", config_path=config_path)
    assert success is True
    assert "removida com sucesso" in msg

    loaded_cfg = load_config(config_path)
    claude_accs = loaded_cfg["agents"]["claude"]["accounts"]
    assert len(claude_accs) == 1
    assert claude_accs[0]["id"] == "default"

    # Codex and Gemini remain untouched
    assert len(loaded_cfg["agents"]["codex"]["accounts"]) == 1
    assert len(loaded_cfg["agents"]["gemini"]["accounts"]) == 1


def test_remove_account_preserves_0600_permissions_and_atomicity(tmp_path):
    config_dir = tmp_path / "custom_config_dir"
    config_path = config_dir / "config.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "acc-1", "name": "Acc 1"},
                    {"id": "acc-2", "name": "Acc 2"},
                ]
            }
        },
    }
    save_config(cfg, config_path)

    # Check initial permissions
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(config_dir).st_mode) == 0o700

    # Remove account
    success, _ = remove_account("claude", "acc-2", config_path=config_path)
    assert success is True

    # Check permissions strictly preserved
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(config_dir).st_mode) == 0o700


def test_remove_account_synchronizes_status_cache(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "acc-1", "name": "Claude 1", "source": "manual"},
                    {"id": "acc-2", "name": "Claude 2", "source": "manual"},
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    # Run collector to produce status.json
    collect_and_save(config_path=config_path, cache_path=cache_path)

    initial_status = load_status_cache(cache_path)
    assert len(initial_status["agents"]["claude"]["accounts"]) == 2

    # Remove acc-2
    success, msg = remove_account("claude", "acc-2", config_path=config_path, cache_path=cache_path)
    assert success is True

    # Check status.json immediately updated
    updated_status = load_status_cache(cache_path)
    assert validate_status_contract(updated_status) is True
    claude_accs = updated_status["agents"]["claude"]["accounts"]
    assert len(claude_accs) == 1
    assert claude_accs[0]["id"] == "acc-1"

    # Status cache maintains 0600
    assert stat.S_IMODE(os.stat(cache_path).st_mode) == 0o600


def test_remove_account_when_status_cache_does_not_exist(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "codex": {
                "accounts": [
                    {"id": "acc-old", "name": "Codex Old"},
                ]
            }
        },
    }
    save_config(cfg, config_path)
    assert not cache_path.exists()

    # Remove account
    success, msg = remove_account("codex", "acc-old", config_path=config_path, cache_path=cache_path)
    assert success is True
    assert "removida com sucesso" in msg

    # Cache file was not created, config was updated
    assert not cache_path.exists()
    loaded_cfg = load_config(config_path)
    assert len(loaded_cfg["agents"]["codex"]["accounts"]) == 0


def test_remove_account_non_existent(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {
        "version": 1,
        "agents": {
            "gemini": {
                "accounts": [
                    {"id": "existing-id", "name": "Gemini Account"}
                ]
            }
        },
    }
    save_config(cfg, config_path)

    # Attempt removal of non-existent account
    success, msg = remove_account("gemini", "ghost-id", config_path=config_path)
    assert success is False
    assert "não encontrada" in msg

    # Config is untouched
    loaded_cfg = load_config(config_path)
    assert len(loaded_cfg["agents"]["gemini"]["accounts"]) == 1


def test_remove_account_invalid_provider(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {"version": 1, "agents": {}}
    save_config(cfg, config_path)

    success, msg = remove_account("unknown_ai", "id-1", config_path=config_path)
    assert success is False
    assert "Provedor inválido" in msg


def test_remove_last_remaining_account_updates_agent_status_to_not_configured(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "only-one", "name": "Only Account"}
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)
    collect_and_save(config_path=config_path, cache_path=cache_path)

    success, _ = remove_account("claude", "only-one", config_path=config_path, cache_path=cache_path)
    assert success is True

    status = load_status_cache(cache_path)
    assert status["agents"]["claude"]["accounts"] == []
    assert status["agents"]["claude"]["status"] == "not_configured"


def test_remove_account_alternative_config_formats():
    # 1. Alternative dict format
    cfg_dict = {
        "accounts": {
            "claude": [
                {"id": "c1", "name": "Account 1"},
                {"id": "c2", "name": "Account 2"},
            ]
        }
    }
    updated, removed = remove_account_from_config(cfg_dict, "claude", "c1")
    assert removed is True
    assert len(updated["accounts"]["claude"]) == 1
    assert updated["accounts"]["claude"][0]["id"] == "c2"

    # 2. Alternative list format
    cfg_list = {
        "accounts": [
            {"provider": "claude", "id": "c1"},
            {"provider": "claude", "id": "c2"},
            {"provider": "codex", "id": "co1"},
        ]
    }
    updated, removed = remove_account_from_config(cfg_list, "claude", "c1")
    assert removed is True
    assert len(updated["accounts"]) == 2
    assert not any(a["provider"] == "claude" and a["id"] == "c1" for a in updated["accounts"])
