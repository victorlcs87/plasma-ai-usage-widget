"""Configuration management for plasma-ai-usage-collector.

Handles loading, saving, and ensuring Unix 0600 permissions for config files.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = Path("~/.config/plasma-ai-usage").expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CACHE_DIR = Path("~/.cache/plasma-ai-usage").expanduser()
DEFAULT_CACHE_PATH = DEFAULT_CACHE_DIR / "status.json"


def ensure_secure_dir(dir_path: str | Path) -> Path:
    """Ensure directory exists and has strict 0700 permissions."""
    path = Path(dir_path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Ensure mode 0700 even if umask created it differently
    current_mode = stat.S_IMODE(os.stat(path).st_mode)
    if current_mode != 0o700:
        os.chmod(path, 0o700)
    return path


def ensure_secure_file(file_path: str | Path) -> Path:
    """Ensure file exists with strict 0600 permissions."""
    path = Path(file_path).expanduser().resolve()
    if path.exists():
        current_mode = stat.S_IMODE(os.stat(path).st_mode)
        if current_mode != 0o600:
            os.chmod(path, 0o600)
    return path


def get_default_config() -> dict[str, Any]:
    """Return the default configuration dictionary."""
    return {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "default",
                        "label": "Claude (Padrão)",
                        "source": "auto",
                        "credential_path": "~/.claude/.credentials.json",
                        "manual_invite_url": None,
                    }
                ]
            },
            "codex": {
                "accounts": [
                    {
                        "id": "default",
                        "label": "Codex (Padrão)",
                        "source": "auto",
                        "credential_path": "~/.codex/auth.json",
                        "manual_invite_url": None,
                    }
                ]
            },
            "gemini": {
                "accounts": [
                    {
                        "id": "default",
                        "label": "Gemini (Padrão)",
                        "source": "auto",
                        "credential_path": "~/.gemini/oauth_creds.json",
                        "manual_invite_url": None,
                    }
                ]
            },
        },
    }


def save_secure_json(data: dict[str, Any], path: str | Path, prefix: str = "tmp_") -> Path:
    """Atomically save dictionary as JSON to file ensuring 0600 permissions."""
    file_path = Path(path).expanduser().resolve()
    ensure_secure_dir(file_path.parent)

    dir_name = file_path.parent
    temp_fd, temp_path_str = tempfile.mkstemp(dir=dir_name, prefix=prefix, suffix=".tmp")
    temp_path = Path(temp_path_str)

    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # Ensure 0600 permissions
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, file_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    ensure_secure_file(file_path)
    return file_path


def save_config(config_data: dict[str, Any], path: str | Path | None = None) -> Path:
    """Atomically save configuration to file ensuring 0600 permissions."""
    file_path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG_PATH
    return save_secure_json(config_data, file_path, prefix="config_")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from file, creating default if not found."""
    file_path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG_PATH
    if not file_path.exists():
        default_cfg = get_default_config()
        save_config(default_cfg, file_path)
        return default_cfg

    ensure_secure_file(file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


def get_accounts_for_agent(config_data: dict[str, Any], agent: str) -> list[dict[str, Any]]:
    """Extract list of accounts for a given agent from config structure."""
    if "agents" in config_data and agent in config_data["agents"]:
        agent_cfg = config_data["agents"][agent]
        if isinstance(agent_cfg, dict) and "accounts" in agent_cfg:
            return agent_cfg["accounts"]
    elif "accounts" in config_data and isinstance(config_data["accounts"], dict):
        if agent in config_data["accounts"]:
            return config_data["accounts"][agent]
    elif "accounts" in config_data and isinstance(config_data["accounts"], list):
        return [acc for acc in config_data["accounts"] if acc.get("provider") == agent]

    return []
