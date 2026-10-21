"""Perfis Orfaos (ADR-0008): Perfis Isolados em disco sem Conta cadastrada.

Listar e reimportar nunca apagam nada; excluir exige confirmacao explicita do chamador.
Migracao, troca e captura nao passam por aqui, entao nunca removem orfaos.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ai_usage_collector.capture import (
    _CREDENTIAL_FILENAMES,
    _merge_label,
    _read_json_dict,
    _store_into_profile,
    account_credential_file,
    get_profiles_base_dir,
)
from ai_usage_collector.config import (
    SUPPORTED_PROVIDERS,
    add_account_to_config,
    config_lock,
    generate_account_slug,
    get_accounts_for_agent,
    load_config,
    save_config,
)
from ai_usage_collector.identity import credential_identity


def _referenced_dirs(cfg: dict[str, Any]) -> set[Path]:
    dirs: set[Path] = set()
    for prov in SUPPORTED_PROVIDERS:
        for acc in get_accounts_for_agent(cfg, prov):
            f = account_credential_file(prov, acc) if isinstance(acc, dict) else None
            if f is not None:
                dirs.add(f.parent)
    return dirs


def list_orphans(config_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Perfis Isolados em `profiles/` que nenhuma Conta cadastrada referencia."""
    cfg = load_config(config_path)
    base = get_profiles_base_dir(config_path)
    used = _referenced_dirs(cfg)
    orphans = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.resolve() in used:
            continue
        for prov in SUPPORTED_PROVIDERS:
            f = d / _CREDENTIAL_FILENAMES[prov]
            if f.is_file():
                ident = credential_identity(prov, f)
                orphans.append({"provider": prov, "id": d.name, "path": str(d), "email": ident.email if ident else None})
                break
    return orphans


def _find(provider: str, name: str, config_path: str | Path | None) -> dict[str, Any] | None:
    return next((o for o in list_orphans(config_path) if o["provider"] == provider.lower().strip() and o["id"] == name), None)


def reimport_orphan(provider: str, name: str, config_path: str | Path | None = None) -> tuple[bool, str]:
    """Cria uma Conta a partir do orfao; se ja houver Conta de mesma identidade, funde nela."""
    with config_lock(config_path):
        orphan = _find(provider, name, config_path)
        if orphan is None:
            return False, f"Perfil órfão '{name}' não encontrado para '{provider}'."
        prov = orphan["provider"]
        cred = Path(orphan["path"]) / _CREDENTIAL_FILENAMES[prov]
        cfg = load_config(config_path)
        accounts = get_accounts_for_agent(cfg, prov)
        ident = credential_identity(prov, cred)
        label = f"{prov.capitalize()} ({ident.email})" if ident and ident.email else f"{prov.capitalize()} ({name})"

        match = next((a for a in accounts if ident and (i := credential_identity(prov, account_credential_file(prov, a))) and i.key == ident.key), None)
        if match is not None:
            creds = _read_json_dict(cred)
            if creds is not None:
                _store_into_profile(prov, creds, cred, account_credential_file(prov, match))  # nunca regride tokens
            _merge_label(prov, match, {"name": label, "label": label})
            save_config(cfg, config_path)
            return True, f"Perfil órfão '{name}' fundido na Conta '{match.get('id')}' (mesma identidade). O perfil órfão não foi apagado."

        entry = {
            "id": generate_account_slug(name, {str(a.get("id")) for a in accounts}),
            "name": label,
            "label": label,
            "source": "captured",
            "credential_path": str(cred),
            f"{prov}_dir": orphan["path"],
        }
        save_config(add_account_to_config(cfg, prov, entry), config_path)
        return True, f"Perfil órfão '{name}' reimportado como Conta '{entry['id']}'."


def delete_orphan(provider: str, name: str, confirm: bool, config_path: str | Path | None = None) -> tuple[bool, str]:
    """Exclui o orfao do disco, somente com `confirm` explicito."""
    if not confirm:
        return False, f"Excluir o perfil órfão '{name}' apaga credenciais do disco; repita com --confirm para confirmar."
    with config_lock(config_path):
        orphan = _find(provider, name, config_path)  # so apaga o que ainda e orfao, dentro de profiles/
        if orphan is None:
            return False, f"Perfil órfão '{name}' não encontrado para '{provider}'."
        shutil.rmtree(orphan["path"])
        return True, f"Perfil órfão '{name}' excluído."
