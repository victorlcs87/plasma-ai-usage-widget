import json
import os
import stat
from ai_usage_collector.config import (
    load_config,
    save_config,
    ensure_secure_file,
    ensure_secure_dir,
    get_default_config,
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

    claude_accounts = cfg["agents"]["claude"]["accounts"]
    assert len(claude_accounts) == 1
    assert claude_accounts[0]["source"] == "auto"
    assert claude_accounts[0]["id"] == "default"


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
