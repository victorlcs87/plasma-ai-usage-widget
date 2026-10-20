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
import subprocess
import sys
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
    ensure_secure_file(cred_file)
    ensure_secure_dir(profile_dir)

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
                ensure_secure_dir(profile_dir)
                ensure_secure_file(cred_file)
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

    updated_cfg = add_account_to_config(cfg, prov, account_entry)
    save_config(updated_cfg, config_path)

    return (
        True,
        f"Login interativo de '{prov}' concluído com sucesso como '{final_label}' ({account_id}) no perfil isolado.",
        account_entry,
    )
