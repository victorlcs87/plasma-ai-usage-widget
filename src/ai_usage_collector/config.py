"""Configuration management for plasma-ai-usage-collector.

Handles loading, saving, and ensuring Unix 0600 permissions for config files.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = Path("~/.config/plasma-ai-usage").expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CACHE_DIR = Path("~/.cache/plasma-ai-usage").expanduser()
DEFAULT_CACHE_PATH = DEFAULT_CACHE_DIR / "status.json"

SUPPORTED_PROVIDERS: tuple[str, ...] = ("claude", "codex", "gemini")


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
    if not isinstance(config_data, dict):
        return []
    if "agents" in config_data and isinstance(config_data["agents"], dict):
        agent_cfg = config_data["agents"].get(agent)
        if isinstance(agent_cfg, dict) and "accounts" in agent_cfg and isinstance(agent_cfg["accounts"], list):
            return agent_cfg["accounts"]
    elif "accounts" in config_data:
        if isinstance(config_data["accounts"], dict):
            acc_list = config_data["accounts"].get(agent)
            if isinstance(acc_list, list):
                return acc_list
        elif isinstance(config_data["accounts"], list):
            return [acc for acc in config_data["accounts"] if isinstance(acc, dict) and acc.get("provider") == agent]

    return []


def add_account_to_config(
    config_data: dict[str, Any],
    provider: str,
    account_data: dict[str, Any],
) -> dict[str, Any]:
    """Add or update an account entry for a provider in config structure."""
    prov = provider.lower().strip()
    if prov not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Provedor '{provider}' não suportado. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    acc_id = account_data.get("id")
    if not acc_id:
        raise ValueError("Dados da conta devem conter um identificador 'id'")

    if "agents" not in config_data or not isinstance(config_data["agents"], dict):
        config_data["agents"] = {}

    if prov not in config_data["agents"] or not isinstance(config_data["agents"][prov], dict):
        config_data["agents"][prov] = {"accounts": []}

    agent_entry = config_data["agents"][prov]
    if "accounts" not in agent_entry or not isinstance(agent_entry["accounts"], list):
        agent_entry["accounts"] = []

    accounts: list[dict[str, Any]] = agent_entry["accounts"]
    found = False
    for i, acc in enumerate(accounts):
        if isinstance(acc, dict) and acc.get("id") == acc_id:
            accounts[i] = {**acc, **account_data}
            found = True
            break

    if not found:
        accounts.append(account_data)

    return config_data


def add_account(
    provider: str,
    account_data: dict[str, Any],
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Add or update an account in config and persist atomically with 0600."""
    cfg = load_config(config_path)
    updated_cfg = add_account_to_config(cfg, provider, account_data)
    save_config(updated_cfg, config_path)
    return updated_cfg


def remove_account_from_config(
    config_data: dict[str, Any],
    provider: str,
    account_id: str,
) -> tuple[dict[str, Any], bool]:
    """Remove an account by provider and id from config structure.

    Returns:
        tuple[dict[str, Any], bool]: (updated_config, was_removed)
    """
    prov = provider.lower().strip()
    if prov not in SUPPORTED_PROVIDERS:
        return config_data, False

    acc_id = account_id.strip()
    if not acc_id:
        return config_data, False

    removed = False

    # Standard format: config["agents"][prov]["accounts"]
    if "agents" in config_data and isinstance(config_data["agents"], dict):
        agent_entry = config_data["agents"].get(prov)
        if isinstance(agent_entry, dict) and "accounts" in agent_entry and isinstance(agent_entry["accounts"], list):
            initial_count = len(agent_entry["accounts"])
            new_accounts = [
                acc for acc in agent_entry["accounts"]
                if not (isinstance(acc, dict) and str(acc.get("id")) == acc_id)
            ]
            if len(new_accounts) < initial_count:
                agent_entry["accounts"] = new_accounts
                removed = True

    # Alternative format 1: config["accounts"][prov] = [...]
    if not removed and "accounts" in config_data and isinstance(config_data["accounts"], dict):
        if prov in config_data["accounts"] and isinstance(config_data["accounts"][prov], list):
            initial_count = len(config_data["accounts"][prov])
            new_accounts = [
                acc for acc in config_data["accounts"][prov]
                if not (isinstance(acc, dict) and str(acc.get("id")) == acc_id)
            ]
            if len(new_accounts) < initial_count:
                config_data["accounts"][prov] = new_accounts
                removed = True

    # Alternative format 2: config["accounts"] = [{"provider": "...", "id": "..."}, ...]
    if not removed and "accounts" in config_data and isinstance(config_data["accounts"], list):
        initial_count = len(config_data["accounts"])
        new_accounts = [
            acc for acc in config_data["accounts"]
            if not (isinstance(acc, dict) and acc.get("provider") == prov and str(acc.get("id")) == acc_id)
        ]
        if len(new_accounts) < initial_count:
            config_data["accounts"] = new_accounts
            removed = True

    return config_data, removed


def generate_account_slug(label: str, existing_ids: set[str] | None = None) -> str:
    """Generate a clean, safe, and unique slug identifier for an account."""
    normalized = unicodedata.normalize("NFKD", str(label or "")).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    if not slug:
        slug = "account"

    if existing_ids is None:
        return slug

    candidate = slug
    counter = 2
    while candidate in existing_ids:
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


def create_account_entry(
    provider: str,
    label: str,
    credential_path: str,
    invite_url: str | None = None,
    total_capacity: int | None = None,
    config_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate, generate unique ID, and persist new account entry in config."""
    prov = provider.lower().strip() if provider else ""
    if prov not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Provedor '{provider}' não suportado. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    clean_label = label.strip() if label else ""
    if not clean_label:
        raise ValueError("Rótulo/nome da conta não pode ser vazio")

    clean_cred = credential_path.strip() if credential_path else ""
    if not clean_cred:
        raise ValueError("Caminho de credenciais não pode ser vazio")

    cfg = load_config(config_path)
    existing_accs = get_accounts_for_agent(cfg, prov)
    existing_ids = {str(a.get("id")) for a in existing_accs if isinstance(a, dict) and a.get("id")}

    unique_slug = generate_account_slug(clean_label, existing_ids)

    account_entry: dict[str, Any] = {
        "id": unique_slug,
        "name": clean_label,
        "label": clean_label,
        "source": "manual",
        "credential_path": clean_cred,
    }

    # If the user passed a directory, also record the provider's specific dir key
    cred_p = Path(clean_cred).expanduser()
    if cred_p.is_dir():
        if prov == "claude":
            account_entry["claude_dir"] = clean_cred
        elif prov == "codex":
            account_entry["codex_dir"] = clean_cred
        elif prov == "gemini":
            account_entry["gemini_dir"] = clean_cred

    if invite_url and str(invite_url).strip():
        account_entry["manual_invite_url"] = str(invite_url).strip()

    if total_capacity is not None:
        try:
            val = int(total_capacity)
            if val > 0:
                account_entry["rate_limit_capacity"] = val
        except (ValueError, TypeError):
            pass

    updated_cfg = add_account_to_config(cfg, prov, account_entry)
    save_config(updated_cfg, config_path)
    return updated_cfg, account_entry
