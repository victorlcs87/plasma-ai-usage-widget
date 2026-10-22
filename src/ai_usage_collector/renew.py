"""Renovacao de Contas inativas antes da consulta (Spec 08).

A CLI da ferramenta, executada no Perfil Isolado, renova o token vencido. No maximo uma vez
por Conta por Intervalo de Atualizacao (estado em refresh_state.json). Falhas sao isoladas por
Conta e registradas so como classe (`cli_missing`, `timeout`, `failed`), nunca com saida da CLI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from ai_usage_collector import refresh
from ai_usage_collector.capture import get_system_credential_file

TIMEOUT_SECONDS = 20


def _run(binary: str, args: list[str], env_name: str, profile: Path) -> None:
    exe = shutil.which(binary)
    if not exe:
        raise FileNotFoundError(binary)
    env = {**os.environ, env_name: str(profile)}
    # Lista de argumentos, sem shell; saida descartada (pode conter dados da Conta)
    proc = subprocess.run(
        [exe, *args], env=env, timeout=TIMEOUT_SECONDS, check=False,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError("exit")


# Gancho por provedor: Codex (#59) e Gemini (#60) entram aqui.
RENEWERS: dict[str, Callable[[Path], None]] = {
    "claude": lambda profile: _run("claude", ["auth", "status"], "CLAUDE_CONFIG_DIR", profile),
}
_PROFILE_KEYS = {"claude": "claude_dir"}


def renew_inactive(
    cyc: refresh.RefreshCycle, provider: str, account_id: str, account: dict[str, Any],
    interval: int, override: Path | None = None,
) -> str | None:
    """Renova o Perfil Isolado da Conta se devido; devolve a classe do erro (None = ok ou nada a fazer)."""
    renewer = RENEWERS.get(provider)
    raw_dir = account.get(_PROFILE_KEYS.get(provider, ""))
    if not renewer or not raw_dir or not cyc.renewal_due(provider, account_id, interval):
        return None
    profile = Path(raw_dir).expanduser().resolve()
    try:
        system_dir = get_system_credential_file(provider, override).resolve().parent
    except Exception:
        system_dir = None
    if system_dir == profile:
        return None  # e a pasta do sistema: nunca tocar
    error = None
    try:
        renewer(profile)
    except FileNotFoundError:
        error = "cli_missing"
    except subprocess.TimeoutExpired:
        error = "timeout"
    except Exception:
        error = "failed"
    cyc.record_renewal(provider, account_id, error)
    if error:
        sys.stderr.write(f"Aviso: renovacao da Conta {provider}:{account_id} falhou ({error})\n")
    return error
