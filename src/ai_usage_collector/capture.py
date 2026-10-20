"""Profile isolation and active CLI session capture for AI providers.

Inspects active authentication credentials for Claude, Codex, and Gemini,
extracts real user identity, clones credentials into an isolated directory
with strict permissions (0700/0600), and registers the account in config.json.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ai_usage_collector.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    SUPPORTED_PROVIDERS,
    add_account_to_config,
    ensure_secure_dir,
    ensure_secure_file,
    generate_account_slug,
    get_accounts_for_agent,
    load_config,
    save_config,
    save_secure_json,
)
from ai_usage_collector.discovery import extract_jwt_identity


def get_profiles_base_dir(config_path: str | Path | None = None) -> Path:
    """Return the base profiles directory (~/.config/plasma-ai-usage/profiles)."""
    if config_path:
        base = Path(config_path).expanduser().resolve().parent / "profiles"
    else:
        base = DEFAULT_CONFIG_DIR / "profiles"
    return ensure_secure_dir(base)


def resolve_profile_slug_and_dir(
    prov: str,
    label: str,
    profiles_dir: Path,
    existing_ids: set[str],
) -> tuple[str, str]:
    """Resolve collision-free account id slug and profile directory name.

    Returns:
        tuple[str, str]: (account_id, directory_name)
    """
    prov_lower = prov.lower().strip()
    base_slug = generate_account_slug(label)

    prefix = f"{prov_lower}-"
    if base_slug.startswith(prefix):
        core = base_slug[len(prefix):]
    else:
        core = base_slug

    candidate_slug = f"{prefix}{core}" if not base_slug.startswith(prefix) else base_slug
    dir_name = candidate_slug

    counter = 2
    while candidate_slug in existing_ids or (profiles_dir / dir_name).exists():
        candidate_slug = f"{prefix}{core}-{counter}"
        dir_name = candidate_slug
        counter += 1

    return candidate_slug, dir_name


def get_active_claude_credentials() -> tuple[dict[str, Any] | None, str]:
    """Retrieve active Claude credentials from file."""
    env_path = os.environ.get("CLAUDE_CREDENTIALS_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
    elif os.environ.get("CLAUDE_CONFIG_DIR"):
        p = Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser().resolve() / ".credentials.json"
    else:
        p = Path("~/.claude/.credentials.json").expanduser().resolve()

    if not p.exists() or not p.is_file():
        return None, str(p)

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data, str(p)
    except Exception:
        pass

    return None, str(p)


def get_active_codex_credentials() -> tuple[dict[str, Any] | None, str]:
    """Retrieve active Codex credentials from file."""
    env_path = os.environ.get("CODEX_AUTH_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
    elif os.environ.get("CODEX_HOME"):
        p = Path(os.environ["CODEX_HOME"]).expanduser().resolve() / "auth.json"
    else:
        p = Path("~/.codex/auth.json").expanduser().resolve()

    if not p.exists() or not p.is_file():
        return None, str(p)

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data, str(p)
    except Exception:
        pass

    return None, str(p)


def get_active_gemini_credentials() -> tuple[dict[str, Any] | None, str]:
    """Retrieve active Gemini credentials from secret-tool keyring or fallback file."""
    env_path = os.environ.get("GEMINI_CREDENTIALS_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data, str(p)
            except Exception:
                pass
        return None, str(p)

    env_dir = os.environ.get("GEMINI_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir).expanduser().resolve() / "oauth_creds.json"
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data, str(p)
            except Exception:
                pass
        return None, str(p)

    # Keyring via secret-tool
    keyring_data = None
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", "service", "gemini", "username", "antigravity"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        if proc.returncode == 0:
            raw = proc.stdout.strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        keyring_data = parsed
                except Exception:
                    pass
                if not keyring_data:
                    keyring_data = {"access_token": raw, "token_type": "Bearer"}
    except Exception:
        pass

    if keyring_data:
        return keyring_data, "keyring (secret-tool)"

    default_p = Path("~/.gemini/oauth_creds.json").expanduser().resolve()
    if default_p.exists() and default_p.is_file():
        try:
            with open(default_p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data, str(default_p)
        except Exception:
            pass

    return None, str(default_p)


def inspect_and_validate_active_session(
    provider: str,
) -> tuple[bool, str, dict[str, Any] | None, str | None, str]:
    """Inspect and validate the active CLI session for the given provider.

    Returns:
        tuple[bool, str, dict[str, Any] | None, str | None, str]:
            (is_valid, error_or_success_message, credentials_data, identity, default_filename)
    """
    prov = provider.lower().strip()
    if prov not in SUPPORTED_PROVIDERS:
        return (
            False,
            f"Provedor '{provider}' não suportado. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}",
            None,
            None,
            "",
        )

    if prov == "claude":
        creds, path_str = get_active_claude_credentials()
        if creds is None:
            return (
                False,
                f"Nenhuma sessão ativa encontrada para Claude em {path_str}. Faça login via 'claude auth login' antes de capturar.",
                None,
                None,
                ".credentials.json",
            )

        oauth = creds.get("claudeAiOauth")
        token = None
        if isinstance(oauth, dict) and oauth.get("accessToken"):
            token = oauth["accessToken"]
        elif creds.get("accessToken"):
            token = creds["accessToken"]

        if not token or not str(token).strip():
            return (
                False,
                f"Sessão Claude inválida ou accessToken ausente em {path_str}. Faça login via 'claude auth login'.",
                None,
                None,
                ".credentials.json",
            )

        # Extract identity
        identity = None
        if isinstance(oauth, dict):
            identity = oauth.get("email") or oauth.get("account", {}).get("email")
        if not identity:
            identity = creds.get("email")
        if not identity:
            identity = extract_jwt_identity(str(token))
        if not identity and isinstance(oauth, dict):
            identity = oauth.get("subscriptionType") or oauth.get("rateLimitTier")

        return True, "Sessão Claude ativa validada.", creds, identity, ".credentials.json"

    elif prov == "codex":
        creds, path_str = get_active_codex_credentials()
        if creds is None:
            return (
                False,
                f"Nenhuma sessão ativa encontrada para Codex em {path_str}. Faça login via 'codex login' antes de capturar.",
                None,
                None,
                "auth.json",
            )

        tokens = creds.get("tokens")
        if not isinstance(tokens, dict):
            return (
                False,
                f"Sessão Codex inválida ou tokens ausentes em {path_str}. Faça login via 'codex login'.",
                None,
                None,
                "auth.json",
            )

        access_token = tokens.get("access_token")
        if not access_token or not str(access_token).strip():
            return (
                False,
                f"Sessão Codex inválida: tokens.access_token ausente em {path_str}. Faça login via 'codex login'.",
                None,
                None,
                "auth.json",
            )

        # Extract identity
        identity = None
        id_token = tokens.get("id_token")
        if id_token:
            identity = extract_jwt_identity(str(id_token))
        if not identity:
            identity = extract_jwt_identity(str(access_token))
        if not identity:
            identity = tokens.get("account_id") or creds.get("account_id") or creds.get("email")

        return True, "Sessão Codex ativa validada.", creds, identity, "auth.json"

    elif prov == "gemini":
        creds, source_info = get_active_gemini_credentials()
        if creds is None:
            return (
                False,
                "Nenhuma sessão ativa encontrada para Gemini no chaveiro do sistema ou em ~/.gemini/oauth_creds.json. Faça login antes de capturar.",
                None,
                None,
                "oauth_creds.json",
            )

        access_token = creds.get("access_token") or creds.get("token") or creds.get("refresh_token")
        if isinstance(access_token, dict):
            access_token = access_token.get("access_token")

        if not access_token or not str(access_token).strip():
            return (
                False,
                "Sessão Gemini inválida: credencial ativa sem token de acesso. Faça login antes de capturar.",
                None,
                None,
                "oauth_creds.json",
            )

        # Extract identity
        identity = creds.get("email")
        if not identity:
            id_token = creds.get("id_token")
            if id_token:
                identity = extract_jwt_identity(str(id_token))
        if not identity and isinstance(access_token, str):
            identity = extract_jwt_identity(access_token)

        return True, "Sessão Gemini ativa validada.", creds, identity, "oauth_creds.json"

    return False, f"Provedor '{provider}' não suportado.", None, None, ""


def capture_current_session(
    provider: str,
    label: str | None = None,
    invite_url: str | None = None,
    total_capacity: int | None = None,
    config_path: str | Path | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Capture active CLI session, isolate into profiles directory, and persist to config.

    Returns:
        tuple[bool, str, dict[str, Any] | None]: (success, status_message, new_account_entry)
    """
    prov = provider.lower().strip()
    if prov not in SUPPORTED_PROVIDERS:
        return (
            False,
            f"Provedor '{provider}' não suportado. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}",
            None,
        )

    valid, err_msg, creds_data, identity, filename = inspect_and_validate_active_session(prov)
    if not valid or creds_data is None:
        return False, err_msg, None

    # Determine final readable label
    if label and str(label).strip():
        final_label = str(label).strip()
    elif identity and str(identity).strip():
        final_label = f"{prov.capitalize()} ({str(identity).strip()})"
    else:
        final_label = f"{prov.capitalize()}"

    profiles_base = get_profiles_base_dir(config_path)

    cfg = load_config(config_path)
    existing_accs = get_accounts_for_agent(cfg, prov)
    existing_ids = {str(a.get("id")) for a in existing_accs if isinstance(a, dict) and a.get("id")}

    account_id, dir_name = resolve_profile_slug_and_dir(
        prov=prov,
        label=final_label,
        profiles_dir=profiles_base,
        existing_ids=existing_ids,
    )

    profile_dir = profiles_base / dir_name
    ensure_secure_dir(profile_dir)

    target_cred_file = profile_dir / filename
    try:
        save_secure_json(creds_data, target_cred_file, prefix="cred_")
    except Exception as e:
        return False, f"Falha ao persistir credencial isolada no perfil: {e}", None

    ensure_secure_file(target_cred_file)

    account_entry: dict[str, Any] = {
        "id": account_id,
        "name": final_label,
        "label": final_label,
        "source": "captured",
        "credential_path": str(target_cred_file),
    }

    if prov == "claude":
        account_entry["claude_dir"] = str(profile_dir)
    elif prov == "codex":
        account_entry["codex_dir"] = str(profile_dir)
    elif prov == "gemini":
        account_entry["gemini_dir"] = str(profile_dir)

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

    return (
        True,
        f"Sessão ativa de '{prov}' capturada com sucesso como '{final_label}' ({account_id}) no perfil isolado.",
        account_entry,
    )
