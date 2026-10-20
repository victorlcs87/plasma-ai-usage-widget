import json
import os
import stat
from ai_usage_collector.config import (
    load_config,
    save_config,
    save_secure_json,
    ensure_secure_file,
    ensure_secure_dir,
    get_default_config,
    rename_account,
    rename_account_in_config,
)


def test_ensure_secure_dir_and_file(tmp_path):
    test_dir = tmp_path / "secure_dir"
    ensure_secure_dir(test_dir)
    dir_mode = stat.S_IMODE(os.stat(test_dir).st_mode)
    assert dir_mode == 0o700

    test_file = test_dir / "secure_file.json"
    with open(test_file, "w") as f:
        f.write("{}")

    # Manually loosen permissions
    os.chmod(test_file, 0o644)
    ensure_secure_file(test_file)
    file_mode = stat.S_IMODE(os.stat(test_file).st_mode)
    assert file_mode == 0o600


def test_load_config_creates_default_when_missing(tmp_path):
    config_path = tmp_path / "plasma-ai-usage" / "config.json"
    assert not config_path.exists()

    cfg = load_config(config_path)

    assert config_path.exists()
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(config_path.parent).st_mode) == 0o700

    assert cfg["version"] == 1
    assert "agents" in cfg
    assert "claude" in cfg["agents"]
    assert "codex" in cfg["agents"]
    assert "gemini" in cfg["agents"]

    # O caminho do sistema nunca e uma Conta (ADR-0008).
    assert cfg["agents"]["claude"]["accounts"] == []


def test_save_config_persists_with_0600(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = get_default_config()
    cfg["custom_key"] = "test_value"

    save_config(cfg, config_path)

    assert config_path.exists()
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600

    with open(config_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["custom_key"] == "test_value"


def test_save_secure_json_atomic_and_permissions(tmp_path):
    target_path = tmp_path / "sub" / "output.json"
    data = {"hello": "world", "number": 42}

    res_path = save_secure_json(data, target_path, prefix="test_")

    assert res_path == target_path.resolve()
    assert target_path.exists()
    assert stat.S_IMODE(os.stat(target_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target_path.parent).st_mode) == 0o700

    with open(target_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_rename_account_in_config_standard_format():
    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "acc-1",
                        "label": "Nome Antigo",
                        "name": "Nome Antigo",
                        "source": "manual",
                        "credential_path": "/path/to/creds",
                        "claude_dir": "/path/to/claude",
                        "manual_invite_url": "https://example.com/invite",
                    }
                ]
            }
        },
    }

    updated_cfg, was_renamed = rename_account_in_config(cfg, "claude", "acc-1", "Novo Nome Incrível")
    assert was_renamed is True
    acc = updated_cfg["agents"]["claude"]["accounts"][0]
    assert acc["label"] == "Novo Nome Incrível"
    assert acc["name"] == "Novo Nome Incrível"
    # Preserves all other attributes
    assert acc["id"] == "acc-1"
    assert acc["source"] == "manual"
    assert acc["credential_path"] == "/path/to/creds"
    assert acc["claude_dir"] == "/path/to/claude"
    assert acc["manual_invite_url"] == "https://example.com/invite"


def test_rename_account_in_config_not_found():
    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "acc-1", "label": "Nome 1"}
                ]
            }
        },
    }
    updated_cfg, was_renamed = rename_account_in_config(cfg, "claude", "non-existent", "Novo Nome")
    assert was_renamed is False
    assert updated_cfg["agents"]["claude"]["accounts"][0]["label"] == "Nome 1"


def test_rename_account_in_config_empty_label():
    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "acc-1", "label": "Nome 1"}
                ]
            }
        },
    }
    updated_cfg, was_renamed = rename_account_in_config(cfg, "claude", "acc-1", "   ")
    assert was_renamed is False
    assert updated_cfg["agents"]["claude"]["accounts"][0]["label"] == "Nome 1"


def test_rename_account_persistence(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {
        "version": 1,
        "agents": {
            "codex": {
                "accounts": [
                    {"id": "codex-1", "label": "Codex Antigo", "source": "auto"}
                ]
            }
        },
    }
    save_config(cfg, config_path)

    updated_cfg, was_renamed = rename_account("codex", "codex-1", "Codex Pro", config_path=config_path)
    assert was_renamed is True
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600

    loaded = load_config(config_path)
    assert loaded["agents"]["codex"]["accounts"][0]["label"] == "Codex Pro"
    assert loaded["agents"]["codex"]["accounts"][0]["name"] == "Codex Pro"
    assert loaded["agents"]["codex"]["accounts"][0]["id"] == "codex-1"
