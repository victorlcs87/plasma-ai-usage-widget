"""Profile isolation and active CLI session capture for AI providers.

Inspects active authentication credentials for Claude, Codex, and Gemini,
extracts real user identity, clones credentials into an isolated directory
with strict permissions (0700/0600), and registers the account in config.json.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ai_usage_collector.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    SUPPORTED_PROVIDERS,
    add_account_to_config,
    config_lock,
    ensure_secure_dir,
    ensure_secure_file,
    generate_account_slug,
    get_accounts_for_agent,
    load_config,
    save_config,
    save_secure_json,
)
from ai_usage_collector.discovery import extract_jwt_identity
from ai_usage_collector.identity import (
    copy_identity_state,
    credential_identity,
    identity_state_file,
    supports_identity,
)


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
    with config_lock(config_path):
        return _capture_current_session(provider, label, invite_url, total_capacity, config_path)


def _capture_current_session(
    provider: str,
    label: str | None,
    invite_url: str | None,
    total_capacity: int | None,
    config_path: str | Path | None,
) -> tuple[bool, str, dict[str, Any] | None]:
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

    sys_file = get_system_credential_file(prov)
    sys_identity = credential_identity(prov, sys_file)
    if sys_identity and sys_identity.email:
        identity = sys_identity.email

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
        copy_identity_state(prov, sys_file, target_cred_file)
    except Exception as e:
        _cleanup_profile_if_empty(profile_dir)
        return False, f"Falha ao persistir credencial isolada no perfil: {e}", None

    enforce_profile_security_permissions(profile_dir)

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

    try:
        updated_cfg = add_account_to_config(cfg, prov, account_entry)
        save_config(updated_cfg, config_path)
    except Exception as e:
        _cleanup_profile_if_empty(profile_dir)
        return False, f"Falha ao salvar configuração: {e}", None

    return (
        True,
        f"Sessão ativa de '{prov}' capturada com sucesso como '{final_label}' ({account_id}) no perfil isolado.",
        account_entry,
    )


def validate_credentials_data(
    provider: str,
    creds: dict[str, Any],
) -> tuple[bool, str, str | None]:
    """Validate parsed credentials dictionary and extract user identity.

    Returns:
        tuple[bool, str, str | None]: (is_valid, status_or_error_message, identity)
    """
    prov = provider.lower().strip()
    if prov == "claude":
        oauth = creds.get("claudeAiOauth")
        token = None
        if isinstance(oauth, dict) and oauth.get("accessToken"):
            token = oauth["accessToken"]
        elif creds.get("accessToken"):
            token = creds["accessToken"]

        if not token or not str(token).strip():
            return False, "Sessão Claude inválida ou accessToken ausente.", None

        identity = None
        if isinstance(oauth, dict):
            identity = oauth.get("email") or oauth.get("account", {}).get("email")
        if not identity:
            identity = creds.get("email")
        if not identity:
            identity = extract_jwt_identity(str(token))
        if not identity and isinstance(oauth, dict):
            identity = oauth.get("subscriptionType") or oauth.get("rateLimitTier")

        return True, "Sessão Claude validada com sucesso.", identity

    elif prov == "codex":
        tokens = creds.get("tokens")
        if not isinstance(tokens, dict):
            return False, "Sessão Codex inválida: tokens ausentes.", None

        access_token = tokens.get("access_token")
        if not access_token or not str(access_token).strip():
            return False, "Sessão Codex inválida: tokens.access_token ausente.", None

        identity = None
        id_token = tokens.get("id_token")
        if id_token:
            identity = extract_jwt_identity(str(id_token))
        if not identity:
            identity = extract_jwt_identity(str(access_token))
        if not identity:
            identity = tokens.get("account_id") or creds.get("account_id") or creds.get("email")

        return True, "Sessão Codex validada com sucesso.", identity

    elif prov == "gemini":
        access_token = creds.get("access_token") or creds.get("token") or creds.get("refresh_token")
        if isinstance(access_token, dict):
            access_token = access_token.get("access_token")

        if not access_token or not str(access_token).strip():
            return False, "Sessão Gemini inválida: credencial sem token de acesso.", None

        identity = creds.get("email")
        if not identity:
            id_token = creds.get("id_token")
            if id_token:
                identity = extract_jwt_identity(str(id_token))
        if not identity and isinstance(access_token, str):
            identity = extract_jwt_identity(access_token)

        return True, "Sessão Gemini validada com sucesso.", identity

    return False, f"Provedor '{provider}' não suportado.", None


def detect_terminal_emulator() -> str | None:
    """Detect available terminal emulator on the system.

    Checks: $TERMINAL, konsole, x-terminal-emulator, gnome-terminal, xterm.
    """
    env_term = os.environ.get("TERMINAL")
    if env_term:
        resolved = shutil.which(env_term)
        if resolved:
            return resolved

    for candidate in ("konsole", "x-terminal-emulator", "gnome-terminal", "xterm"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    return None


def build_login_command_for_provider(provider: str, profile_dir: Path) -> tuple[str, dict[str, str]]:
    """Build the isolated login command string and environment variables for the provider.

    Returns:
        tuple[str, dict[str, str]]: (command_string, environment_variables)
    """
    prov = provider.lower().strip()
    profile_path = str(profile_dir.expanduser().resolve())

    if prov == "claude":
        return f"env CLAUDE_CONFIG_DIR={shlex.quote(profile_path)} claude auth login", {"CLAUDE_CONFIG_DIR": profile_path}
    elif prov == "codex":
        return f"env CODEX_HOME={shlex.quote(profile_path)} codex login", {"CODEX_HOME": profile_path}
    elif prov == "gemini":
        return "agy", {"GEMINI_CONFIG_DIR": profile_path}
    else:
        raise ValueError(f"Provedor não suportado para login interativo: '{provider}'")


def build_terminal_exec_args(terminal_bin: str, command_str: str) -> list[str]:
    """Build the argument list to run command_str inside the given terminal emulator."""
    term_name = Path(terminal_bin).name.lower()
    if "gnome-terminal" in term_name:
        return [terminal_bin, "--", "bash", "-c", command_str]
    else:
        # konsole, x-terminal-emulator, xterm, etc.
        return [terminal_bin, "-e", "bash", "-c", command_str]


def enforce_profile_security_permissions(profile_dir: Path) -> None:
    """Recursively enforce 0700 on directories and 0600 on files within profile_dir."""
    if not profile_dir.exists():
        return
    ensure_secure_dir(profile_dir)
    for p in profile_dir.rglob("*"):
        if p.is_dir():
            ensure_secure_dir(p)
        elif p.is_file():
            ensure_secure_file(p)


def _cleanup_profile_if_empty(profile_dir: Path) -> None:
    """Remove profile directory if empty or containing no valid credentials."""
    if profile_dir.exists() and profile_dir.is_dir():
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass


def inspect_and_validate_profile_credentials(
    provider: str,
    profile_dir: Path,
) -> tuple[bool, str, dict[str, Any] | None, str | None, Path | None]:
    """Inspect and validate credentials file generated in an isolated profile directory.

    Returns:
        tuple[bool, str, dict[str, Any] | None, str | None, Path | None]:
            (is_valid, message, credentials_data, identity, credential_file_path)
    """
    prov = provider.lower().strip()
    if prov not in SUPPORTED_PROVIDERS:
        return False, f"Provedor '{provider}' não suportado.", None, None, None

    if prov == "claude":
        target = profile_dir / ".credentials.json"
        if not target.exists() or not target.is_file():
            return False, f"Arquivo de credenciais não encontrado em {target}.", None, None, None
        try:
            with open(target, "r", encoding="utf-8") as f:
                creds = json.load(f)
        except Exception as e:
            return False, f"Erro ao ler {target}: {e}", None, None, None

        valid, msg, identity = validate_credentials_data(prov, creds)
        if not valid:
            return False, msg, None, None, None
        return True, msg, creds, identity, target

    elif prov == "codex":
        target = profile_dir / "auth.json"
        if not target.exists() or not target.is_file():
            return False, f"Arquivo de autenticação não encontrado em {target}.", None, None, None
        try:
            with open(target, "r", encoding="utf-8") as f:
                creds = json.load(f)
        except Exception as e:
            return False, f"Erro ao ler {target}: {e}", None, None, None

        valid, msg, identity = validate_credentials_data(prov, creds)
        if not valid:
            return False, msg, None, None, None
        return True, msg, creds, identity, target

    elif prov == "gemini":
        target = profile_dir / "oauth_creds.json"
        if target.exists() and target.is_file():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    creds = json.load(f)
                valid, msg, identity = validate_credentials_data(prov, creds)
                if valid:
                    return True, msg, creds, identity, target
            except Exception:
                pass

        # Check if agy stored credentials in keyring or default ~/.gemini/oauth_creds.json
        creds, _ = get_active_gemini_credentials()
        if creds is not None:
            valid, msg, identity = validate_credentials_data(prov, creds)
            if valid:
                try:
                    save_secure_json(creds, target, prefix="gemini_")
                    ensure_secure_file(target)
                    return True, msg, creds, identity, target
                except Exception as e:
                    return False, f"Falha ao persistir credenciais Gemini no perfil: {e}", None, None, None

        return False, "Credenciais Gemini não encontradas no perfil isolado nem no chaveiro.", None, None, None

    return False, f"Provedor '{provider}' não suportado.", None, None, None


def run_interactive_login(
    provider: str,
    label: str | None = None,
    no_terminal: bool = False,
    invite_url: str | None = None,
    total_capacity: int | None = None,
    config_path: str | Path | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Execute interactive login in an isolated profile directory, extract identity, and persist account.

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

    profiles_base = get_profiles_base_dir(config_path)
    cfg = load_config(config_path)
    existing_accs = get_accounts_for_agent(cfg, prov)
    existing_ids = {str(a.get("id")) for a in existing_accs if isinstance(a, dict) and a.get("id")}

    clean_label = label.strip() if label and str(label).strip() else None
    initial_slug_label = clean_label or f"{prov.capitalize()}"
    account_id, dir_name = resolve_profile_slug_and_dir(
        prov=prov,
        label=initial_slug_label,
        profiles_dir=profiles_base,
        existing_ids=existing_ids,
    )

    profile_dir = profiles_base / dir_name
    ensure_secure_dir(profile_dir)

    login_cmd, extra_env = build_login_command_for_provider(prov, profile_dir)
    env = os.environ.copy()
    env.update(extra_env)

    # Launch login process
    if no_terminal:
        try:
            subprocess.run(
                ["bash", "-c", login_cmd],
                env=env,
                check=False,
            )
        except Exception as e:
            _cleanup_profile_if_empty(profile_dir)
            return False, f"Falha ao executar login interativo diretamente: {e}", None
    else:
        term = detect_terminal_emulator()
        if not term:
            if sys.stdin.isatty():
                # Fallback to direct execution in current TTY
                try:
                    subprocess.run(
                        ["bash", "-c", login_cmd],
                        env=env,
                        check=False,
                    )
                except Exception as e:
                    _cleanup_profile_if_empty(profile_dir)
                    return False, f"Falha ao executar login interativo: {e}", None
            else:
                _cleanup_profile_if_empty(profile_dir)
                return (
                    False,
                    "Nenhum emulador de terminal compatível encontrado (konsole, x-terminal-emulator, gnome-terminal, xterm). Instale o Konsole ou use --no-terminal.",
                    None,
                )
        else:
            term_args = build_terminal_exec_args(term, login_cmd)
            try:
                subprocess.run(
                    term_args,
                    env=env,
                    check=False,
                )
            except Exception as e:
                _cleanup_profile_if_empty(profile_dir)
                return False, f"Falha ao abrir emulador de terminal '{term}': {e}", None

    # Validate generated credentials in profile_dir
    valid, val_msg, creds_data, identity, cred_file = inspect_and_validate_profile_credentials(prov, profile_dir)
    if not valid or cred_file is None:
        _cleanup_profile_if_empty(profile_dir)
        return (
            False,
            f"Nenhuma credencial gerada ou válida no perfil isolado para '{prov}' após o login interativo. Autenticação cancelada ou incompleta.",
            None,
        )

    # Enforce secure permissions 0600 on credential file and 0700 on profile directory
    enforce_profile_security_permissions(profile_dir)

    # Determine final label and rename profile dir if appropriate
    if clean_label:
        final_label = clean_label
    elif identity and str(identity).strip():
        final_label = f"{prov.capitalize()} ({str(identity).strip()})"
    else:
        final_label = f"{prov.capitalize()}"

    # If label was not user-provided and an identity was discovered, refine slug and directory name
    if not clean_label and identity:
        final_account_id, final_dir_name = resolve_profile_slug_and_dir(
            prov=prov,
            label=final_label,
            profiles_dir=profiles_base,
            existing_ids=existing_ids,
        )
        if final_dir_name != dir_name and not (profiles_base / final_dir_name).exists():
            final_profile_dir = profiles_base / final_dir_name
            try:
                profile_dir.rename(final_profile_dir)
                profile_dir = final_profile_dir
                account_id = final_account_id
                cred_file = profile_dir / cred_file.name
                enforce_profile_security_permissions(profile_dir)
            except Exception:
                pass

    account_entry: dict[str, Any] = {
        "id": account_id,
        "name": final_label,
        "label": final_label,
        "source": "interactive_login",
        "credential_path": str(cred_file),
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

    try:
        with config_lock(config_path):  # recarrega: evita lost-update durante o login demorado
            updated_cfg = add_account_to_config(load_config(config_path), prov, account_entry)
            save_config(updated_cfg, config_path)
    except Exception as e:
        _cleanup_profile_if_empty(profile_dir)
        return False, f"Falha ao salvar configuração: {e}", None

    return (
        True,
        f"Login interativo de '{prov}' concluído com sucesso como '{final_label}' ({account_id}) no perfil isolado.",
        account_entry,
    )


def get_system_credential_file(provider: str) -> Path:
    """Return default system credentials file path for provider, respecting env overrides."""
    prov = provider.lower().strip()
    if prov == "claude":
        env_path = os.environ.get("CLAUDE_CREDENTIALS_PATH")
        if env_path:
            p = Path(env_path).expanduser()
            return p.parent.resolve() / p.name  # preserva symlink do arquivo
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            return Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser().resolve() / ".credentials.json"
        return Path("~/.claude").expanduser().resolve() / ".credentials.json"
    elif prov == "codex":
        env_path = os.environ.get("CODEX_AUTH_PATH")
        if env_path:
            return Path(env_path).expanduser().resolve()
        if os.environ.get("CODEX_HOME"):
            return Path(os.environ["CODEX_HOME"]).expanduser().resolve() / "auth.json"
        return Path("~/.codex/auth.json").expanduser().resolve()
    elif prov == "gemini":
        env_path = os.environ.get("GEMINI_CREDENTIALS_PATH")
        if env_path:
            return Path(env_path).expanduser().resolve()
        if os.environ.get("GEMINI_CONFIG_DIR"):
            return Path(os.environ["GEMINI_CONFIG_DIR"]).expanduser().resolve() / "oauth_creds.json"
        return Path("~/.gemini/oauth_creds.json").expanduser().resolve()
    raise ValueError(f"Provedor '{provider}' não suportado.")


def _extract_credential_signature(provider: str, creds: dict[str, Any] | None) -> dict[str, Any]:
    """Extract comparable tokens and identity attributes from credentials dictionary."""
    if not isinstance(creds, dict):
        return {}

    prov = provider.lower().strip()
    sig: dict[str, Any] = {
        "access_token": None,
        "refresh_token": None,
        "id_token": None,
        "email": None,
        "account_id": None,
    }

    if prov == "claude":
        oauth = creds.get("claudeAiOauth")
        if isinstance(oauth, dict):
            sig["access_token"] = oauth.get("accessToken")
            sig["refresh_token"] = oauth.get("refreshToken")
            sig["email"] = oauth.get("email") or oauth.get("account", {}).get("email")
            sig["account_id"] = oauth.get("accountId") or oauth.get("account", {}).get("id")
        if not sig["access_token"]:
            sig["access_token"] = creds.get("accessToken")
        if not sig["refresh_token"]:
            sig["refresh_token"] = creds.get("refreshToken")
        if not sig["email"]:
            sig["email"] = creds.get("email")
        if not sig["email"] and sig["access_token"]:
            sig["email"] = extract_jwt_identity(str(sig["access_token"]))

    elif prov == "codex":
        tokens = creds.get("tokens")
        if isinstance(tokens, dict):
            sig["access_token"] = tokens.get("access_token")
            sig["refresh_token"] = tokens.get("refresh_token")
            sig["id_token"] = tokens.get("id_token")
            sig["account_id"] = tokens.get("account_id")
        if not sig["access_token"]:
            sig["access_token"] = creds.get("access_token")
        if not sig["refresh_token"]:
            sig["refresh_token"] = creds.get("refresh_token")
        if not sig["account_id"]:
            sig["account_id"] = creds.get("account_id")
        if sig["id_token"]:
            sig["email"] = extract_jwt_identity(str(sig["id_token"]))
        if not sig["email"] and sig["access_token"]:
            sig["email"] = extract_jwt_identity(str(sig["access_token"]))
        if not sig["email"]:
            sig["email"] = creds.get("email")

    elif prov == "gemini":
        tok_dict = creds.get("token") if isinstance(creds.get("token"), dict) else {}
        sig["access_token"] = tok_dict.get("access_token") or creds.get("access_token")
        sig["refresh_token"] = tok_dict.get("refresh_token") or creds.get("refresh_token")
        sig["id_token"] = tok_dict.get("id_token") or creds.get("id_token")
        sig["email"] = creds.get("email")
        if not sig["email"] and sig["id_token"]:
            sig["email"] = extract_jwt_identity(str(sig["id_token"]))
        if not sig["email"] and isinstance(sig["access_token"], str):
            sig["email"] = extract_jwt_identity(sig["access_token"])

    return sig


def _signatures_match(sig1: dict[str, Any], sig2: dict[str, Any]) -> bool:
    """Check if two credential signatures correspond to the same account."""
    if not sig1 or not sig2:
        return False

    # 1. Match by refresh token (strongest persistent identity across renewals)
    if sig1.get("refresh_token") and sig2.get("refresh_token") and sig1["refresh_token"] == sig2["refresh_token"]:
        return True

    # 2. Match by email
    if sig1.get("email") and sig2.get("email") and str(sig1["email"]).lower() == str(sig2["email"]).lower():
        return True

    # 3. Match by account_id
    if sig1.get("account_id") and sig2.get("account_id") and str(sig1["account_id"]) == str(sig2["account_id"]):
        return True

    # 4. Match by access token
    if sig1.get("access_token") and sig2.get("access_token") and sig1["access_token"] == sig2["access_token"]:
        return True

    return False


_CREDENTIAL_FILENAMES = {"claude": ".credentials.json", "codex": "auth.json", "gemini": "oauth_creds.json"}


def _read_json_dict(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_active_credentials(provider: str) -> dict[str, Any] | None:
    """Credencial atualmente aplicada no sistema para o provedor (ou None)."""
    prov = provider.lower().strip()
    if prov == "claude":
        return get_active_claude_credentials()[0]
    if prov == "codex":
        return get_active_codex_credentials()[0]
    if prov == "gemini":
        return get_active_gemini_credentials()[0]
    return None


def account_credential_file(provider: str, account: dict[str, Any]) -> Path | None:
    """Arquivo de credencial do Perfil Isolado de uma Conta."""
    prov = provider.lower().strip()
    val = account.get("credential_path") or account.get("credentials_path")
    if not val and account.get(f"{prov}_dir"):
        val = str(Path(account[f"{prov}_dir"]) / _CREDENTIAL_FILENAMES.get(prov, ""))
    return Path(val).expanduser().resolve() if val else None


def find_matching_account(
    provider: str,
    accounts: list[dict[str, Any]],
    creds: dict[str, Any] | None,
    cred_file: Path,
) -> dict[str, Any] | None:
    """Conta que corresponde a credencial em `cred_file`.

    Ordem: (1) igualdade exata de refresh/access token com um Perfil Isolado, que prevalece
    sobre metadados de identidade possivelmente defasados; (2) Identidade da Conta;
    (3) assinatura por email/token, so para Contas sem identidade conhecida.
    Nos provedores com Identidade da Conta, a propria `cred_file` nunca e uma Conta; os
    demais (Gemini ate o ticket 20) mantem o comportamento anterior.
    """
    prov = provider.lower().strip()
    target = cred_file.expanduser().resolve()
    exclude_system = supports_identity(prov)
    sig = _extract_credential_signature(prov, creds) if creds else {}
    candidates = []
    for acc in accounts:
        f = account_credential_file(prov, acc)
        if f is not None and f.is_file() and not (exclude_system and f == target):
            candidates.append((acc, f, _extract_credential_signature(prov, _read_json_dict(f))))

    for acc, _, acc_sig in candidates:
        for key in ("refresh_token", "access_token"):
            if sig.get(key) and sig[key] == acc_sig.get(key):
                return acc

    ident = credential_identity(prov, target)
    if ident:
        for acc, f, _ in candidates:
            acc_ident = credential_identity(prov, f)
            if acc_ident and acc_ident.key == ident.key:
                return acc

    for acc, f, acc_sig in candidates:
        if ident and credential_identity(prov, f):
            continue
        if sig and _signatures_match(sig, acc_sig):
            return acc
    return None


def _expires_at(creds: dict[str, Any] | None) -> float:
    oauth = (creds or {}).get("claudeAiOauth")
    val = oauth.get("expiresAt") if isinstance(oauth, dict) else None
    return float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else 0.0


def _store_into_profile(
    provider: str,
    creds: dict[str, Any],
    src_file: Path,
    profile_file: Path,
    copy_identity: bool = False,
) -> None:
    """Grava a credencial do sistema no Perfil Isolado de uma Conta.

    A identidade (`oauthAccount`) so e copiada com `copy_identity`, isto e, na criacao de um
    perfil novo: um perfil existente casado por token nunca ganha a identidade do sistema,
    que pode estar defasada. Nunca regride tokens: se o perfil tem `expiresAt` mais novo,
    a credencial recebida vai so para um `.bak-<timestamp>`. Se o perfil tinha outra
    credencial, ela e preservada antes em `.bak-<timestamp>`.
    """
    current = _read_json_dict(profile_file)
    if current is not None and _expires_at(current) > _expires_at(creds) > 0:
        _write_bak(profile_file, json.dumps(creds).encode("utf-8"))
        return
    _backup_profile_credential(profile_file, creds)
    save_secure_json(creds, profile_file, prefix="backup_")
    if copy_identity:
        copy_identity_state(provider, src_file, profile_file)
    enforce_profile_security_permissions(profile_file.parent)


PROFILE_BACKUPS_KEPT = 5


def _write_bak(profile_file: Path, data: bytes) -> None:
    bak = profile_file.with_name(f"{profile_file.name}.bak-{time.time_ns()}")
    fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # nasce 0600
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    for old in sorted(profile_file.parent.glob(f"{profile_file.name}.bak-*"))[:-PROFILE_BACKUPS_KEPT]:
        old.unlink(missing_ok=True)


def _backup_profile_credential(profile_file: Path, new_creds: dict[str, Any]) -> None:
    if not profile_file.is_file() or _read_json_dict(profile_file) == new_creds:
        return
    _write_bak(profile_file, profile_file.read_bytes())


def _snapshot(paths: list[Path | None]) -> list[tuple[Path, bytes | None, int]]:
    snap = []
    for p in paths:
        if p is None:
            continue
        p = p.resolve()  # restaura no alvo real de symlinks
        if p.is_file():
            snap.append((p, p.read_bytes(), stat.S_IMODE(p.stat().st_mode)))
        else:
            snap.append((p, None, 0))
    return snap


def _restore(snap: list[tuple[Path, bytes | None, int]]) -> list[str]:
    """Restaura os arquivos do snapshot; devolve os caminhos que nao puderam ser restaurados."""
    failed: list[str] = []
    for path, data, mode in snap:
        try:
            if data is None:
                path.unlink(missing_ok=True)
                continue
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rollback_", suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except Exception:
            failed.append(str(path))
    return failed


def switch_system_account(
    provider: str,
    account_id: str,
    config_path: str | Path | None = None,
) -> tuple[bool, str, bool]:
    """Alternancia de Conta (ADR-0008), com rollback do sistema em caso de falha.

    1. Le a credencial do sistema e obtem sua identidade.
    2. Faz backup no Perfil Isolado da Conta correspondente ou a captura como Conta nova.
    3. Aplica a credencial da Conta escolhida no sistema (0600) junto de sua identidade.

    Serializado com as demais escritas da configuracao por `config_lock`.

    Returns:
        tuple[bool, str, bool]: (success, status_message, already_active)
    """
    with config_lock(config_path):
        return _switch_system_account(provider, account_id, config_path)


def _switch_system_account(
    provider: str,
    account_id: str,
    config_path: str | Path | None,
) -> tuple[bool, str, bool]:
    prov = provider.lower().strip() if provider else ""
    if prov not in SUPPORTED_PROVIDERS:
        return False, f"Provedor '{provider}' não suportado. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}", False

    acc_id = str(account_id).strip() if account_id is not None else ""
    cfg = load_config(config_path)
    accounts = get_accounts_for_agent(cfg, prov)
    target_acc = next((a for a in accounts if str(a.get("id")) == acc_id), None)
    if not target_acc:
        return False, f"Conta '{account_id}' não encontrada no provedor '{provider}'.", False

    source_file = account_credential_file(prov, target_acc)
    if source_file is None:
        return False, f"Caminho de credenciais não configurado para a conta '{account_id}'.", False
    if _read_json_dict(source_file) is None:
        return False, f"Arquivo de credenciais da conta '{account_id}' ausente ou inválido em '{source_file}'.", False

    sys_file = get_system_credential_file(prov)
    if sys_file.is_file() and _read_json_dict(sys_file) is None:
        return False, f"Credencial do sistema em '{sys_file}' está ilegível; troca abortada para não perdê-la.", False

    # Passos 1 e 2: backup da credencial atual do sistema
    sys_creds = get_active_credentials(prov)
    if sys_creds is not None:
        match = find_matching_account(prov, accounts, sys_creds, sys_file)
        if match is not None:
            match_file = account_credential_file(prov, match)
            if match_file != sys_file.resolve():  # conta legada no proprio caminho (Gemini)
                try:
                    _store_into_profile(prov, sys_creds, sys_file, match_file)
                except Exception as e:
                    return False, f"Falha ao realizar backup da conta ativa no sistema para '{match.get('id')}': {e}", False
            if match is target_acc:
                # Conta ja ativa: reaplicar o perfil gravaria tokens possivelmente ja rotacionados.
                return True, f"Conta '{account_id}' já está ativa no sistema; credencial sincronizada no Perfil Isolado.", True
        else:
            ok, msg, _ = capture_current_session(prov, config_path=config_path)
            if not ok:
                return False, f"Credencial desconhecida no sistema não pôde ser capturada antes da troca: {msg}", False

    # Passo 3: aplicar a Conta escolhida (lida apos o backup), restaurando o sistema em falha
    target_creds = _read_json_dict(source_file)
    if target_creds is None:
        return False, f"Arquivo de credenciais da conta '{account_id}' ausente ou inválido em '{source_file}'.", False
    snapshot = _snapshot([sys_file, identity_state_file(prov, sys_file)])
    try:
        save_secure_json(target_creds, sys_file, prefix=f"{prov}_sys_")
        copy_identity_state(prov, source_file, sys_file)
    except Exception as e:
        failed = _restore(snapshot)
        if failed:
            return False, (
                f"Falha ao aplicar a conta '{account_id}' no sistema: {e}. "
                f"ATENÇÃO: não foi possível restaurar {', '.join(failed)}."
            ), False
        return False, f"Falha ao aplicar a conta '{account_id}' no sistema (estado anterior restaurado): {e}", False

    # For Gemini, update system keyring via secret-tool
    if prov == "gemini":
        try:
            raw_payload = json.dumps(target_creds, ensure_ascii=False)
            subprocess.run(
                [
                    "secret-tool",
                    "store",
                    "--label=Antigravity Token",
                    "service",
                    "gemini",
                    "username",
                    "antigravity",
                ],
                input=raw_payload,
                text=True,
                capture_output=True,
                timeout=3.0,
                check=False,
            )
        except Exception:
            pass

    return True, f"Conta '{account_id}' ativada com sucesso no sistema para '{provider}'.", False


def _auto_label(provider: str, cred_file: Path | None) -> str:
    """Rotulo que o sistema gera para a Conta: 'Provedor (email)' ou 'Provedor'."""
    ident = credential_identity(provider, cred_file)
    name = provider.capitalize()
    return f"{name} ({ident.email})" if ident and ident.email else name


def _is_auto_label(provider: str, label: str | None, cred_file: Path | None) -> bool:
    """So e automatico o rotulo que bate exatamente com um dos gerados pelo sistema para a Conta."""
    text = (label or "").strip()
    name = provider.capitalize()
    generated = {"", name, f"{name} (Padrão)", _auto_label(provider, cred_file)}
    oauth = (_read_json_dict(cred_file) or {}).get("claudeAiOauth") if cred_file else None
    if isinstance(oauth, dict):
        for key in ("subscriptionType", "rateLimitTier"):  # fallback da captura sem email
            if oauth.get(key):
                generated.add(f"{name} ({oauth[key]})")
    return text in generated


def _merge_label(provider: str, keep: dict[str, Any], other: dict[str, Any]) -> None:
    """Na fusao, prevalece o rotulo renomeado pelo usuario."""
    keep_label = keep.get("name") or keep.get("label")
    other_label = other.get("name") or other.get("label")
    keep_auto = _is_auto_label(provider, keep_label, account_credential_file(provider, keep))
    other_auto = _is_auto_label(provider, other_label, account_credential_file(provider, other))
    if keep_auto and not other_auto:
        keep["label"] = other_label
        keep["name"] = other_label


def _migrate_provider(
    prov: str,
    accounts: list[dict[str, Any]],
    config_path: str | Path | None,
    created: list[Path],
) -> bool:
    changed = False
    sys_file = get_system_credential_file(prov)  # sem resolver: symlink define o estado ao lado

    # 1. Entradas legadas apontando para o caminho do sistema viram Perfil Isolado.
    for acc in list(accounts):
        if account_credential_file(prov, acc) != sys_file.resolve():
            continue
        sys_creds = _read_json_dict(sys_file)
        if sys_creds is None and sys_file.is_file():
            continue  # ilegivel (transitorio?): adia a migracao em vez de apagar a entrada
        changed = True
        if sys_creds is None:
            accounts.remove(acc)  # o caminho do sistema nunca e, por si so, uma Conta
            continue
        others = [a for a in accounts if a is not acc]
        match = find_matching_account(prov, others, sys_creds, sys_file)
        if match is not None:
            _merge_label(prov, match, acc)  # antes do backup: compara com o rotulo gerado do perfil
            _store_into_profile(prov, sys_creds, sys_file, account_credential_file(prov, match))
            accounts.remove(acc)
            continue
        ident = credential_identity(prov, sys_file)
        if _is_auto_label(prov, acc.get("name") or acc.get("label"), sys_file):
            acc["label"] = acc["name"] = _auto_label(prov, sys_file)
        profiles_base = get_profiles_base_dir(config_path)
        existing_ids = {str(a.get("id")) for a in others}
        slug_label = f"{prov.capitalize()} ({ident.email})" if ident and ident.email else (acc.get("label") or prov)
        _, dir_name = resolve_profile_slug_and_dir(prov, slug_label, profiles_base, existing_ids)
        profile_dir = ensure_secure_dir(profiles_base / dir_name)
        created.append(profile_dir)
        profile_file = profile_dir / _CREDENTIAL_FILENAMES[prov]
        _store_into_profile(prov, sys_creds, sys_file, profile_file, copy_identity=True)
        acc.pop("credentials_path", None)
        acc["credential_path"] = str(profile_file)
        acc[f"{prov}_dir"] = str(profile_dir)

    # 2. Fusao de Contas com a mesma identidade e o mesmo refresh token (Perfis dos duplicados ficam como Orfaos).
    seen: dict[str, dict[str, Any]] = {}
    for acc in list(accounts):
        f = account_credential_file(prov, acc)
        ident = credential_identity(prov, f)
        if ident is None:
            continue
        keep = seen.get(ident.key)
        if keep is None:
            seen[ident.key] = acc
            continue
        keep_file = account_credential_file(prov, keep)
        if _refresh_token(prov, f) != _refresh_token(prov, keep_file):
            continue  # tokens divergentes: nunca sobrescrever credenciais na fusao automatica
        _merge_label(prov, keep, acc)
        accounts.remove(acc)
        changed = True

    return changed


def _refresh_token(provider: str, cred_file: Path | None) -> Any:
    return _extract_credential_signature(provider, _read_json_dict(cred_file)).get("refresh_token")


def migrate_accounts(config_data: dict[str, Any], config_path: str | Path) -> bool:
    """Migracao idempotente da configuracao (ADR-0008); altera `config_data` e a salva.

    Remove o campo legado `active` (deixou de ser fonte de verdade) e, nos provedores com
    Identidade da Conta, migra entradas do caminho do sistema e funde duplicatas. Em falha,
    remove os Perfis Isolados criados nesta execucao e propaga o erro.

    Returns:
        bool: True se a configuracao foi alterada e salva.
    """
    with config_lock(config_path):
        return _migrate_accounts(config_data, config_path)


def _migrate_accounts(config_data: dict[str, Any], config_path: str | Path) -> bool:
    changed = False
    created: list[Path] = []
    try:
        for prov in SUPPORTED_PROVIDERS:
            accounts = get_accounts_for_agent(config_data, prov)
            for acc in accounts:
                if isinstance(acc, dict) and "active" in acc:
                    del acc["active"]
                    changed = True
            if supports_identity(prov) and accounts:
                changed = _migrate_provider(prov, accounts, config_path, created) or changed
        if changed:
            save_config(config_data, config_path)
    except Exception:
        for d in created:
            shutil.rmtree(d, ignore_errors=True)
        raise
    return changed
