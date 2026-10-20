"""Core collector engine coordinating config, discovery, and canonical status generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from ai_usage_collector.capture import (
    activate_profile_to_system,
    backup_active_to_profile,
    get_active_claude_credentials,
    get_active_codex_credentials,
    get_active_gemini_credentials,
    get_system_credential_file,
    _extract_credential_signature,
    _signatures_match,
)
from ai_usage_collector.config import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CONFIG_PATH,
    SUPPORTED_PROVIDERS,
    create_account_entry,
    get_accounts_for_agent,
    load_config,
    remove_account_from_config,
    rename_account as config_rename_account,
    save_config,
    save_secure_json,
    set_active_account,
)
from ai_usage_collector.contract import (
    build_agent_account_status,
    build_empty_status_contract,
    get_current_iso_timestamp,
)
from ai_usage_collector.discovery import discover_account
from ai_usage_collector.history import apply_token_history
from ai_usage_collector.extractors import (
    extract_claude_status,
    extract_codex_status,
    extract_gemini_status,
)


def save_status_cache(status_data: dict[str, Any], path: str | Path | None = None) -> Path:
    """Save status.json payload atomically with secure permissions (0600)."""
    file_path = Path(path).expanduser().resolve() if path else DEFAULT_CACHE_PATH
    return save_secure_json(status_data, file_path, prefix="status_")


def load_status_cache(path: str | Path | None = None) -> dict[str, Any] | None:
    """Load cached status.json if exists."""
    file_path = Path(path).expanduser().resolve() if path else DEFAULT_CACHE_PATH
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def detect_active_account_id(provider: str, accounts: list[dict[str, Any]]) -> str | None:
    """Detect which account is currently active in the system for the given provider."""
    if not accounts:
        return None

    prov = provider.lower().strip()
    if prov == "claude":
        sys_creds, _ = get_active_claude_credentials()
    elif prov == "codex":
        sys_creds, _ = get_active_codex_credentials()
    elif prov == "gemini":
        sys_creds, _ = get_active_gemini_credentials()
    else:
        sys_creds = None

    sys_file = None
    try:
        sys_file = get_system_credential_file(prov).resolve()
    except Exception:
        pass

    sys_sig = _extract_credential_signature(prov, sys_creds) if sys_creds else {}

    # Check 1: If system credentials exist, check signature match against account credential files
    if sys_sig:
        for acc in accounts:
            cred_p_val = acc.get("credential_path") or acc.get("credentials_path")
            if not cred_p_val:
                dir_key = f"{prov}_dir"
                if acc.get(dir_key):
                    filename = ".credentials.json" if prov == "claude" else ("auth.json" if prov == "codex" else "oauth_creds.json")
                    cred_p_val = str(Path(acc[dir_key]) / filename)

            if cred_p_val:
                p = Path(cred_p_val).expanduser().resolve()
                if p.exists() and p.is_file():
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            acc_data = json.load(f)
                        if isinstance(acc_data, dict):
                            acc_sig = _extract_credential_signature(prov, acc_data)
                            if _signatures_match(sys_sig, acc_sig):
                                return str(acc.get("id"))
                    except Exception:
                        pass

    # Check 2: If system file exists and matches an account's credential_path
    if sys_file and sys_file.exists() and sys_creds is not None:
        for acc in accounts:
            cred_p_val = acc.get("credential_path") or acc.get("credentials_path")
            if cred_p_val and Path(cred_p_val).expanduser().resolve() == sys_file:
                return str(acc.get("id"))

    # If system credentials exist but matched none of the registered accounts,
    # no account is marked active to prevent false positives (Spec 04).
    return None


def collect_and_save(
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute on-demand collection and write canonical status.json."""
    config = load_config(config_path)
    now_dt = now or datetime.now(timezone.utc)
    status_payload = build_empty_status_contract(now_iso=now_dt.isoformat())

    agents_to_collect = ["claude", "codex", "gemini"]

    for agent_id in agents_to_collect:
        accounts = get_accounts_for_agent(config, agent_id)
        account_statuses: list[dict[str, Any]] = []

        agent_has_valid_account = False
        active_acc_id = detect_active_account_id(agent_id, accounts)

        for acc in accounts:
            acc_id = acc.get("id", "default")
            is_active = (str(acc_id) == str(active_acc_id)) if active_acc_id is not None else False
            acc_name = acc.get("name")
            acc_label = acc.get("label")
            label = acc_name or acc_label or f"{agent_id.capitalize()} ({acc_id})"
            source = acc.get("source", "auto")
            cred_path = acc.get("credential_path") or acc.get("credentials_path")
            if not cred_path:
                if agent_id == "claude" and acc.get("claude_dir"):
                    cred_path = str(Path(acc["claude_dir"]).expanduser().resolve() / ".credentials.json")
                elif agent_id == "codex" and acc.get("codex_dir"):
                    cred_path = str(Path(acc["codex_dir"]).expanduser().resolve() / "auth.json")
                elif agent_id == "gemini" and acc.get("gemini_dir"):
                    cred_path = str(Path(acc["gemini_dir"]).expanduser().resolve() / "oauth_creds.json")

            manual_invite = acc.get("manual_invite_url")
            manual_invite_count = acc.get("manual_invite_count")

            health = discover_account(agent_id, cred_path, account_data=acc)
            native_window = None
            weekly_window = None
            invites = None

            if agent_id == "claude":
                claude_data = extract_claude_status(acc, initial_health=health, now=now_dt)
                health = claude_data.get("health", health)
                native_window = claude_data.get("native_window")
                weekly_window = claude_data.get("weekly_window")
                invites = claude_data.get("free_trial_invites")
            elif agent_id == "codex":
                codex_data = extract_codex_status(acc, initial_health=health, now=now_dt)
                health = codex_data.get("health", health)
                native_window = codex_data.get("native_window")
                weekly_window = codex_data.get("weekly_window")
                invites = codex_data.get("free_trial_invites")
            elif agent_id == "gemini":
                gemini_data = extract_gemini_status(acc, initial_health=health, now=now_dt)
                health = gemini_data.get("health", health)
                native_window = gemini_data.get("native_window")
                weekly_window = gemini_data.get("weekly_window")
                invites = gemini_data.get("free_trial_invites")

            if health.get("status") == "valid":
                agent_has_valid_account = True
                # If label was generic and user identity or subscription was discovered, enrich label display
                meta = health.get("metadata", {})
                if not acc_name and (label.endswith("(Padrão)") or label == f"{agent_id.capitalize()} ({acc_id})"):
                    if meta.get("email"):
                        label = f"{agent_id.capitalize()} ({meta['email']})"
                    elif meta.get("subscription_type"):
                        label = f"{agent_id.capitalize()} ({meta['subscription_type'].capitalize()})"

            acc_status = build_agent_account_status(
                provider=agent_id,
                account_id=acc_id,
                label=label,
                source=source,
                health=health,
                manual_invite_url=manual_invite,
                native_window=native_window,
                weekly_window=weekly_window,
                free_trial_invites=invites,
                name=acc_name or label,
                manual_invite_count=manual_invite_count,
                is_active=is_active,
            )
            account_statuses.append(acc_status)

        status_payload["agents"][agent_id]["accounts"] = account_statuses
        if account_statuses:
            if agent_has_valid_account:
                status_payload["agents"][agent_id]["status"] = "ok"
            else:
                # Check if all missing or error
                all_missing = all(
                    a["health"].get("status") == "missing_credentials" for a in account_statuses
                )
                if all_missing:
                    status_payload["agents"][agent_id]["status"] = "missing_credentials"
                else:
                    status_payload["agents"][agent_id]["status"] = "warning"
        else:
            status_payload["agents"][agent_id]["status"] = "not_configured"

    try:
        apply_token_history(status_payload, config, cache_path, now_dt)
    except Exception as e:  # Historico de Tokens e opcional; nunca impede o status
        sys.stderr.write(f"Aviso: Historico de Tokens nao atualizado: {e}\n")

    # Save to disk
    save_status_cache(status_payload, cache_path)
    return status_payload


def remove_account_from_cache(
    cache_data: dict[str, Any],
    provider: str,
    account_id: str,
) -> tuple[dict[str, Any], bool]:
    """Remove an account by provider and id from cache structure.

    Returns:
        tuple[dict[str, Any], bool]: (updated_cache, was_removed)
    """
    prov = provider.lower().strip()
    acc_id = account_id.strip()

    if not isinstance(cache_data, dict) or "agents" not in cache_data or not isinstance(cache_data["agents"], dict):
        return cache_data, False

    agent_entry = cache_data["agents"].get(prov)
    if not isinstance(agent_entry, dict) or "accounts" not in agent_entry:
        return cache_data, False

    accounts = agent_entry.get("accounts")
    if not isinstance(accounts, list):
        return cache_data, False

    initial_count = len(accounts)
    new_accounts = [
        acc for acc in accounts
        if not (isinstance(acc, dict) and str(acc.get("id")) == acc_id)
    ]

    if len(new_accounts) == initial_count:
        return cache_data, False

    agent_entry["accounts"] = new_accounts

    # Update agent health status
    if not new_accounts:
        agent_entry["status"] = "not_configured"
    else:
        has_valid = any(
            isinstance(a, dict) and a.get("health", {}).get("status") == "valid"
            for a in new_accounts
        )
        if has_valid:
            agent_entry["status"] = "ok"
        else:
            all_missing = all(
                isinstance(a, dict) and a.get("health", {}).get("status") == "missing_credentials"
                for a in new_accounts
            )
            agent_entry["status"] = "missing_credentials" if all_missing else "warning"

    cache_data["last_updated"] = get_current_iso_timestamp()
    return cache_data, True


def remove_account(
    provider: str,
    account_id: str,
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
) -> tuple[bool, str]:
    """Remove an account from config and synchronize with status cache.

    Returns:
        tuple[bool, str]: (success, status_message)
    """
    prov = provider.lower().strip()
    if prov not in SUPPORTED_PROVIDERS:
        return False, f"Provedor inválido '{provider}'. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}"

    acc_id = account_id.strip()
    if not acc_id:
        return False, "Identificador da conta não pode ser vazio"

    cfg_file = Path(config_path).expanduser().resolve() if config_path else DEFAULT_CONFIG_PATH
    if not cfg_file.exists():
        return False, f"Arquivo de configuração não encontrado: {cfg_file}"

    try:
        config_data = load_config(cfg_file)
    except Exception as e:
        return False, f"Falha ao ler arquivo de configuração: {e}"

    updated_cfg, was_removed = remove_account_from_config(config_data, prov, acc_id)
    if not was_removed:
        return False, f"Conta '{account_id}' não encontrada no provedor '{provider}'."

    # Persist config atomically with 0600
    save_config(updated_cfg, cfg_file)

    # Sync cache if exists
    c_file = Path(cache_path).expanduser().resolve() if cache_path else DEFAULT_CACHE_PATH
    if c_file.exists():
        cache_data = load_status_cache(c_file)
        if cache_data is not None:
            updated_cache, cache_removed = remove_account_from_cache(cache_data, prov, acc_id)
            if cache_removed:
                save_status_cache(updated_cache, c_file)

    return True, f"Conta '{account_id}' removida com sucesso do provedor '{provider}'."


def rename_account(
    provider: str,
    account_id: str,
    new_label: str,
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Rename an account in config and synchronize with status cache.

    Returns:
        tuple[bool, str, dict[str, Any] | None]: (success, status_message, status_payload)
    """
    prov = provider.lower().strip() if provider else ""
    if prov not in SUPPORTED_PROVIDERS:
        return (
            False,
            f"Provedor inválido '{provider}'. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}",
            None,
        )

    acc_id = str(account_id).strip() if account_id is not None else ""
    if not acc_id:
        return False, "Identificador da conta não pode ser vazio", None

    clean_label = str(new_label).strip() if new_label is not None else ""
    if not clean_label:
        return False, "Rótulo/nome da conta não pode ser vazio", None

    cfg_file = Path(config_path).expanduser().resolve() if config_path else DEFAULT_CONFIG_PATH
    if not cfg_file.exists():
        return False, f"Arquivo de configuração não encontrado: {cfg_file}", None

    try:
        updated_cfg, was_renamed = config_rename_account(
            provider=prov,
            account_id=acc_id,
            new_label=clean_label,
            config_path=cfg_file,
        )
    except Exception as e:
        return False, f"Falha ao renomear conta no arquivo de configuração: {e}", None

    if not was_renamed:
        return False, f"Conta '{account_id}' não encontrada no provedor '{provider}'.", None

    # Sync status cache via collect_and_save
    try:
        status_payload = collect_and_save(config_path=config_path, cache_path=cache_path)
    except Exception as e:
        return (
            True,
            f"Conta '{clean_label}' renomeada com sucesso, mas falhou ao sincronizar status: {e}",
            None,
        )

    return True, f"Conta '{clean_label}' renomeada com sucesso!", status_payload


def add_account_entry(
    provider: str,
    label: str,
    credential_path: str,
    invite_url: str | None = None,
    total_capacity: int | None = None,
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Add a new account to config and immediately sync status cache.

    Returns:
        tuple[bool, str, dict[str, Any] | None]: (success, status_message, status_payload)
    """
    prov = provider.lower().strip() if provider else ""
    if prov not in SUPPORTED_PROVIDERS:
        return (
            False,
            f"Provedor inválido '{provider}'. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}",
            None,
        )

    clean_label = label.strip() if label else ""
    if not clean_label:
        return False, "Rótulo/nome da conta não pode ser vazio", None

    clean_cred = credential_path.strip() if credential_path else ""
    if not clean_cred:
        return False, "Caminho de credenciais não pode ser vazio", None

    try:
        updated_cfg, new_acc = create_account_entry(
            provider=prov,
            label=clean_label,
            credential_path=clean_cred,
            invite_url=invite_url,
            total_capacity=total_capacity,
            config_path=config_path,
        )
    except Exception as e:
        return False, f"Falha ao salvar configuração da conta: {e}", None

    # Immediately execute collection and update status cache
    try:
        status_payload = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)
    except Exception as e:
        return (
            True,
            f"Conta '{clean_label}' ({new_acc['id']}) adicionada à configuração, mas falhou ao sincronizar status: {e}",
            None,
        )

    return (
        True,
        f"Conta '{clean_label}' ({new_acc['id']}) adicionada com sucesso ao provedor '{prov}'.",
        status_payload,
    )


def capture_current_account(
    provider: str,
    label: str | None = None,
    invite_url: str | None = None,
    total_capacity: int | None = None,
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Capture active CLI session, isolate credentials in profile, and sync status cache.

    Returns:
        tuple[bool, str, dict[str, Any] | None]: (success, status_message, status_payload)
    """
    from ai_usage_collector.capture import capture_current_session

    success, message, new_acc = capture_current_session(
        provider=provider,
        label=label,
        invite_url=invite_url,
        total_capacity=total_capacity,
        config_path=config_path,
    )
    if not success or new_acc is None:
        return False, message, None

    # Immediately execute collection and update status cache
    try:
        status_payload = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)
    except Exception as e:
        return (
            True,
            f"{message} (Aviso: falha ao sincronizar status: {e})",
            None,
        )

    return True, message, status_payload


def interactive_login_account(
    provider: str,
    label: str | None = None,
    no_terminal: bool = False,
    invite_url: str | None = None,
    total_capacity: int | None = None,
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Execute interactive login in isolated profile and sync status cache.

    Returns:
        tuple[bool, str, dict[str, Any] | None]: (success, status_message, status_payload)
    """
    from ai_usage_collector.capture import run_interactive_login

    success, message, new_acc = run_interactive_login(
        provider=provider,
        label=label,
        no_terminal=no_terminal,
        invite_url=invite_url,
        total_capacity=total_capacity,
        config_path=config_path,
    )
    if not success or new_acc is None:
        return False, message, None

    # Immediately execute collection and update status cache
    try:
        status_payload = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)
    except Exception as e:
        return (
            True,
            f"{message} (Aviso: falha ao sincronizar status: {e})",
            None,
        )

    return True, message, status_payload


def switch_account(
    provider: str,
    account_id: str,
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Switch active account in system and sync config and status cache.

    Steps:
        1. Validate provider and account existence.
        2. Backup current active session to its isolated profile.
        3. Activate selected account credentials to system paths.
        4. Persist active account flag in config.
        5. Collect and save updated status.

    Returns:
        tuple[bool, str, dict[str, Any] | None]: (success, status_message, status_payload)
    """
    prov = provider.lower().strip() if provider else ""
    if prov not in SUPPORTED_PROVIDERS:
        return (
            False,
            f"Provedor inválido '{provider}'. Provedores válidos: {', '.join(SUPPORTED_PROVIDERS)}",
            None,
        )

    acc_id = str(account_id).strip() if account_id is not None else ""
    if not acc_id:
        return False, "Identificador da conta não pode ser vazio.", None

    cfg = load_config(config_path)
    accounts = get_accounts_for_agent(cfg, prov)
    target_acc = next((a for a in accounts if str(a.get("id")) == acc_id), None)
    if not target_acc:
        return False, f"Conta '{account_id}' não encontrada no provedor '{provider}'.", None

    # Step 2: Backup active account in system to its matching profile
    backup_ok, backup_msg = backup_active_to_profile(prov, config_path)
    if not backup_ok:
        return False, f"Falha ao realizar backup da conta ativa no sistema: {backup_msg}", None

    # Step 3: Activate target account to system
    act_ok, act_msg = activate_profile_to_system(prov, acc_id, config_path)
    if not act_ok:
        return False, f"Falha ao ativar conta no sistema: {act_msg}", None

    # Step 4: Persist active account flag in config
    set_active_account(prov, acc_id, config_path)

    # Step 5: Collect and save updated status
    target_label = target_acc.get("label") or target_acc.get("name") or acc_id
    try:
        status_payload = collect_and_save(config_path=config_path, cache_path=cache_path)
    except Exception as e:
        return (
            True,
            f"Conta '{target_label}' ativada com sucesso no sistema, mas falhou ao sincronizar status: {e}",
            None,
        )

    return True, f"Conta '{target_label}' ativada com sucesso no sistema!", status_payload



