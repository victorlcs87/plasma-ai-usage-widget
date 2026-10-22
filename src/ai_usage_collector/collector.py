"""Core collector engine coordinating config, discovery, and canonical status generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from ai_usage_collector import refresh, renew, updates
from ai_usage_collector.orphans import list_orphans
from ai_usage_collector.capture import (
    find_matching_account,
    get_active_credentials,
    get_system_credential_file,
    switch_system_account,
    sync_gemini_from_antigravity,
)
from ai_usage_collector.config import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CONFIG_PATH,
    SUPPORTED_PROVIDERS,
    config_lock,
    create_account_entry,
    credential_override,
    get_accounts_for_agent,
    load_config,
    provider_settings,
    remove_account_from_config,
    rename_account as config_rename_account,
    save_config,
    save_secure_json,
)
from ai_usage_collector.contract import (
    build_agent_account_status,
    build_empty_status_contract,
    get_current_iso_timestamp,
)
from ai_usage_collector.discovery import discover_account
from ai_usage_collector.identity import credential_identity
from ai_usage_collector.history import apply_token_history, flush_system_history
from ai_usage_collector.limit_changes import apply_limit_changes
from ai_usage_collector.notifications import apply_notifications, deliver, notify_settings
from ai_usage_collector.running import apply_running, visibility_settings
from ai_usage_collector.pace import alert_settings, apply_pace, reapply_levels
from ai_usage_collector.session_state import apply_session_state
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


def detect_active_account_id(provider: str, accounts: list[dict[str, Any]], override: Path | None = None) -> str | None:
    """Detect the Conta Ativa no Sistema by Identidade da Conta (ADR-0008).

    The `active` config field is not consulted. If the system credential matches no
    registered account, no account is marked active (Spec 04).
    """
    if not accounts:
        return None
    prov = provider.lower().strip()
    sys_creds = get_active_credentials(prov, override)
    if sys_creds is None:
        return None
    match = find_matching_account(prov, accounts, sys_creds, get_system_credential_file(prov, override))
    return str(match.get("id")) if match else None


def collect_and_save(
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    now: datetime | None = None,
    providers: list[str] | None = None,
    intervals: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Collect and write canonical status.json (ADR-0007).

    `providers` limits the collection; the others are kept from the previous status.json.
    `intervals` (seconds per provider) defines each account's next check.
    """
    cache_file = Path(cache_path).expanduser().resolve() if cache_path else DEFAULT_CACHE_PATH
    now_dt = now or refresh.utcnow()
    outbox: list[dict[str, Any]] = []
    update_plan: dict[str, bool] = {}
    with refresh.cycle(cache_file.with_name(refresh.STATE_FILENAME), now_dt) as cyc:
        status_payload = _collect(config_path, cache_file, now_dt, providers, intervals or {}, cyc, outbox, update_plan)
        save_status_cache(status_payload, cache_file)
    deliver(outbox, cache_file)  # fora do lock: D-Bus lento nao segura o status.json
    if update_plan:
        _finish_updates(update_plan, config_path, cache_file, status_payload)  # idem: rede e --version fora do lock
    return status_payload


def _finish_updates(plan: dict[str, bool], config_path: str | Path | None, cache_file: Path, payload: dict[str, Any]) -> None:
    """Rede e `--version` sem o lock; depois mescla so a chave `updates` do status.json atual, sob o lock."""
    try:
        results, local = updates.run_plan(plan, cache_file)
        with refresh.status_lock(cache_file.with_name(refresh.STATE_FILENAME)):
            config = load_config(config_path)
            items = updates.merge_results(cache_file, results, local, config)
            status = load_status_cache(cache_file)
            if isinstance(status, dict) and isinstance(status.get("updates"), dict):
                # enabled sempre da configuracao atual (pode ter sido desligada durante a consulta)
                status["updates"] = {"enabled": updates.update_check_enabled(config), "items": items}
                save_status_cache(status, cache_file)
                payload["updates"] = status["updates"]
    except Exception as e:  # verificacao de atualizacao e opcional; falha de rede nunca chega aqui (e silenciosa)
        sys.stderr.write(f"Aviso: Verificacao de atualizacao nao processada: {e}\n")


def _collect(
    config_path: str | Path | None,
    cache_file: Path,
    now_dt: datetime,
    providers: list[str] | None,
    intervals: dict[str, int],
    cyc: refresh.RefreshCycle,
    outbox: list[dict[str, Any]],
    update_plan: dict[str, bool] | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    status_payload = build_empty_status_contract(now_iso=now_dt.isoformat())
    previous_status = load_status_cache(cache_file)
    previous_agents = (previous_status or {}).get("agents") or {}

    agents_to_collect = ["claude", "codex", "gemini"]

    for agent_id in agents_to_collect:
        if providers and agent_id not in providers and isinstance(previous_agents.get(agent_id), dict):
            status_payload["agents"][agent_id] = previous_agents[agent_id]
            continue
        previous_accounts = {
            str(a.get("id")): a
            for a in (previous_agents.get(agent_id) or {}).get("accounts") or []
            if isinstance(a, dict)
        }
        interval = intervals.get(agent_id, refresh.DEFAULT_INTERVAL_SECONDS)
        accounts = get_accounts_for_agent(config, agent_id)
        account_statuses: list[dict[str, Any]] = []

        agent_has_valid_account = False
        active_acc_id = detect_active_account_id(agent_id, accounts, credential_override(agent_id, config))

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

            if agent_id == "gemini" and source == "captured" and cred_path:
                try:
                    sync_gemini_from_antigravity(Path(cred_path))  # copia isolada acompanha o token vivo
                except Exception as e:
                    sys.stderr.write(f"Aviso: Gemini {acc_id} nao sincronizado com a Antigravity: {type(e).__name__}\n")
            cyc.begin_account(agent_id, str(acc_id))
            if not is_active:  # nunca a Conta Ativa no Sistema: quem a renova e a propria CLI
                renew.renew_inactive(cyc, agent_id, str(acc_id), acc, interval, credential_override(agent_id, config))
            health = discover_account(agent_id, cred_path, account_data=acc)
            native_window = None
            weekly_window = None
            invites = None
            usage_details = None

            if agent_id == "claude":
                claude_data = extract_claude_status(acc, initial_health=health, now=now_dt, api=provider_settings(config, "claude"))
                health = claude_data.get("health", health)
                native_window = claude_data.get("native_window")
                weekly_window = claude_data.get("weekly_window")
                invites = claude_data.get("free_trial_invites")
                usage_details = claude_data.get("usage_details")
            elif agent_id == "codex":
                codex_data = extract_codex_status(acc, initial_health=health, now=now_dt)
                health = codex_data.get("health", health)
                native_window = codex_data.get("native_window")
                weekly_window = codex_data.get("weekly_window")
                invites = codex_data.get("free_trial_invites")
                usage_details = codex_data.get("usage_details")
            elif agent_id == "gemini":
                gemini_data = extract_gemini_status(acc, initial_health=health, now=now_dt)
                health = gemini_data.get("health", health)
                native_window = gemini_data.get("native_window")
                weekly_window = gemini_data.get("weekly_window")
                invites = gemini_data.get("free_trial_invites")
                usage_details = gemini_data.get("usage_details")

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
                usage_details=usage_details,
            )
            outcome = cyc.take_outcome()
            identity = credential_identity(agent_id, cred_path) if outcome and cred_path else None
            refresh.apply_outcome(
                acc_status, outcome, previous_accounts.get(str(acc_id)), now_dt, interval,
                identity_key=identity.key if identity else None,
            )
            if (
                agent_id == "gemini" and "no_data" not in acc_status
                and all(acc_status[w].get("usage_percentage") is None for w in ("native_window", "weekly_window"))
            ):  # token ausente/vencido ou API muda: sem dados, nunca 0% (leitura local e so auxiliar)
                acc_status["no_data"] = True
            account_statuses.append(acc_status)

        status_payload["agents"][agent_id]["accounts"] = account_statuses
        refresh.summarize_agent(status_payload["agents"][agent_id])
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
        status_payload["orphan_profiles"] = list_orphans(config_path)
    except OSError as e:  # Perfis Orfaos sao opcionais; nunca impedem o status
        sys.stderr.write(f"Aviso: Perfis Orfaos nao listados: {e}\n")
        status_payload["orphan_profiles"] = []

    try:
        apply_token_history(status_payload, config, cache_file, now_dt)
    except Exception as e:  # Historico de Tokens e opcional; nunca impede o status
        sys.stderr.write(f"Aviso: Historico de Tokens nao atualizado: {e}\n")

    try:
        apply_limit_changes(status_payload, previous_status, now_dt)
    except Exception as e:  # nota de mudanca de limites e opcional; nunca impede o status
        sys.stderr.write(f"Aviso: Nota de mudanca de limites nao atualizada: {e}\n")

    try:
        apply_pace(status_payload, config, cache_file, now_dt, {a for a in agents_to_collect if not providers or a in providers})
    except Exception as e:  # ritmo e previsao sao opcionais; nunca impedem o status
        sys.stderr.write(f"Aviso: Ritmo de Uso e previsao nao atualizados: {e}\n")

    try:
        apply_session_state(status_payload, config, cache_file, now_dt.timestamp())
    except Exception as e:  # Estado da Sessao e opcional; nunca impede o status
        sys.stderr.write(f"Aviso: Estado da Sessao nao atualizado: {e}\n")

    try:
        apply_notifications(status_payload, config, cache_file, now_dt, {a for a in agents_to_collect if not providers or a in providers}, outbox)
    except Exception as e:  # notificacoes sao opcionais; nunca impedem o status
        sys.stderr.write(f"Aviso: Notificacoes de limite nao processadas: {e}\n")

    apply_running(status_payload, config, now_dt)  # nunca levanta: detect_running trata todo erro de /proc

    try:
        plan = updates.plan_updates(status_payload, config, cache_file, now_dt)
        if update_plan is not None:
            update_plan.update(plan)
    except Exception as e:  # verificacao de atualizacao e opcional; nunca impede o status (falha de rede e silenciosa)
        sys.stderr.write(f"Aviso: Verificacao de atualizacao nao processada: {e}\n")

    return status_payload


def reapply_alert_levels(config_path: str | Path | None = None, cache_path: str | Path | None = None) -> None:
    """Reaplica modo/limiares de alerta e as configuracoes de notificacao ao status.json existente, sem consultar os provedores."""
    cache_file = Path(cache_path).expanduser().resolve() if cache_path else DEFAULT_CACHE_PATH
    with refresh.status_lock(cache_file.with_name(refresh.STATE_FILENAME)):
        status = load_status_cache(cache_file)
        if isinstance(status, dict) and isinstance(status.get("agents"), dict):
            config = load_config(config_path)
            reapply_levels(status, alert_settings(config))
            status["notifications"] = notify_settings(config)  # a tela de configuracao le daqui
            updates.apply_updates(status, config, cache_file)  # idem; sem rede
            status["visibility"] = visibility_settings(config)
            save_status_cache(status, cache_file)


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

    c_file = Path(cache_path).expanduser().resolve() if cache_path else DEFAULT_CACHE_PATH
    # Mesmo lock do ciclo de coleta: um ciclo em andamento nao regrava a conta removida
    with refresh.status_lock(c_file.with_name(refresh.STATE_FILENAME)):
        return _remove_account_locked(prov, acc_id, account_id, provider, cfg_file, c_file)


def _remove_account_locked(
    prov: str, acc_id: str, account_id: str, provider: str, cfg_file: Path, c_file: Path
) -> tuple[bool, str]:
    with config_lock(cfg_file):  # read-modify-write sob o lock
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
    refresh.forget_account(c_file.with_name(refresh.STATE_FILENAME), prov, acc_id)
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
        2. Backup system credential to the matching profile (or capture it as a new account).
        3. Apply selected account credentials to system paths (rollback on failure).
        4. Collect and save updated status.

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

    # Antes de trocar a credencial, atribui o consumo dos logs do sistema a identidade que esta saindo.
    try:
        flush_system_history(cfg, cache_path, datetime.now(timezone.utc))
    except Exception as e:  # Historico e opcional; nunca impede a troca
        sys.stderr.write(f"Aviso: Historico de Tokens nao atualizado: {e}\n")

    # Steps 2-4: backup/capture current system credential, apply target (rollback on failure)
    ok, msg, already_active = switch_system_account(prov, acc_id, config_path)
    if not ok:
        return False, msg, None

    # Step 4: Collect and save updated status
    target_label = target_acc.get("label") or target_acc.get("name") or acc_id
    done = (
        f"Conta '{target_label}' já está ativa no sistema; credencial sincronizada no Perfil Isolado."
        if already_active
        else f"Conta '{target_label}' ativada com sucesso no sistema!"
    )
    try:
        status_payload = collect_and_save(config_path=config_path, cache_path=cache_path)
    except Exception as e:
        return True, f"{done} (Aviso: falhou ao sincronizar status: {e})", None

    return True, done, status_payload



