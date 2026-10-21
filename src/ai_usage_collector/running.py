"""Processo da CLI de cada provedor em execucao (ticket 37), lido de /proc com a stdlib.

Contrato: `agents.<p>.running` = True | False | None (None = nao foi possivel determinar), mais
`running_checked_at` e `visibility.hide_when_not_running` no topo. O QML so esconde com False explicito.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_usage_collector.config import SUPPORTED_PROVIDERS
from ai_usage_collector.refresh import status_lock, utcnow

PROC_ROOT = "/proc"  # injetavel nos testes
CACHE_SECONDS = 5  # varreduras mais proximas reaproveitam o resultado gravado no status.json
HIDE_MODES = ("off", "widget", "provider")
_INTERPRETERS = {"node", "nodejs", "bun"}


def validate_visibility(mode: Any) -> str | None:
    return None if mode in HIDE_MODES else f"Modo inválido. Válidos: {', '.join(HIDE_MODES)}."


def visibility_settings(config: Any) -> dict[str, str]:
    raw = config.get("visibility") if isinstance(config, dict) else None
    mode = raw.get("hide_when_not_running") if isinstance(raw, dict) else None
    return {"hide_when_not_running": mode if mode in HIDE_MODES else "off"}


def _program(cmdline: bytes) -> str:
    """Nome do programa: basename de argv[0], ou do script em argv[1] quando argv[0] e node/bun."""
    argv = cmdline.split(b"\0")
    name = os.path.basename(argv[0].decode(errors="replace"))
    if name in _INTERPRETERS and len(argv) > 1:
        name = os.path.basename(argv[1].decode(errors="replace"))  # flag => nao e um provedor
    return name


def detect_running() -> dict[str, bool | None]:
    """Provedor -> processo do usuario atual em execucao. /proc ilegivel => tudo None; nunca False por erro."""
    unknown = {p: None for p in SUPPORTED_PROVIDERS}
    try:
        entries = [e for e in os.listdir(PROC_ROOT) if e.isdigit()]
    except OSError:
        return unknown
    uid, seen, found, blind = os.getuid(), 0, set(), False
    for pid in entries:
        d = os.path.join(PROC_ROOT, pid)
        try:
            if os.stat(d).st_uid != uid:
                continue
            with open(os.path.join(d, "cmdline"), "rb") as f:
                cmd = f.read()
        except (FileNotFoundError, ProcessLookupError):
            continue  # sumiu durante a leitura
        except OSError:
            blind = True  # processo nosso que nao deu para ler: a ausencia deixa de ser prova
            continue
        seen += 1
        found.add(_program(cmd))
    if seen == 0:
        return unknown
    return {p: True if p in found else (None if blind else False) for p in SUPPORTED_PROVIDERS}


def apply_running(status: dict[str, Any], config: Any, now: datetime) -> None:
    """Grava `running` por provedor, o instante da leitura e a opcao de ocultar no status."""
    for provider, value in detect_running().items():
        if isinstance(status["agents"].get(provider), dict):
            status["agents"][provider]["running"] = value
    status["running_checked_at"] = now.isoformat()
    status["visibility"] = visibility_settings(config)


def refresh_running(config: Any, cache_path: Path) -> None:
    """Atualiza so os campos de execucao do status.json existente (sem consultar provedores); cache curto."""
    from ai_usage_collector.collector import load_status_cache, save_status_cache
    from ai_usage_collector import refresh

    with status_lock(cache_path.with_name(refresh.STATE_FILENAME)):
        status = load_status_cache(cache_path)
        if not (isinstance(status, dict) and isinstance(status.get("agents"), dict)):
            return
        now = utcnow()
        try:
            age = (now - datetime.fromisoformat(status["running_checked_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = CACHE_SECONDS
        if 0 <= age < CACHE_SECONDS:
            return
        apply_running(status, config, now)
        save_status_cache(status, cache_path)
