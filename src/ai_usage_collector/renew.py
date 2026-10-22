"""Renovacao de Contas inativas antes da consulta (Spec 08).

A CLI da ferramenta, executada no Perfil Isolado, renova o token vencido. No maximo uma vez
por Conta por Intervalo de Atualizacao (estado em refresh_state.json). Falhas sao isoladas por
Conta e registradas so como classe (`cli_missing`, `timeout`, `failed`), nunca com saida da CLI.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
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


def _codex_refresh(profile: Path) -> None:
    """Pede ao app-server do Codex (CODEX_HOME = Perfil Isolado) `account/read` com refreshToken.

    Teste real (22/10/2026, copia de perfil com id_token vencido): `codex login status`, `doctor`
    e `debug models` NAO renovam o token; so o JSON-RPC `account/read {refreshToken: true}` do
    `codex app-server` renova (reescreve auth.json, sem gastar tokens de modelo). O app-server
    sai ao fechar o stdin, entao o processo fica aberto ate a resposta (id 2) ou o timeout.
    """
    exe = shutil.which("codex")
    if not exe:
        raise FileNotFoundError("codex")
    proc = subprocess.Popen(
        [exe, "app-server", "--listen", "stdio://"], env={**os.environ, "CODEX_HOME": str(profile)},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        msgs = [
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "ai-usage-widget", "version": "0"}}},
            {"method": "initialized"},
            {"id": 2, "method": "account/read", "params": {"refreshToken": True}},
        ]
        proc.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
        proc.stdin.flush()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        fd, buf = proc.stdout.fileno(), b""  # buffer proprio: select no fd cru nao enxerga o buffer do TextIOWrapper
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([fd], [], [], left)[0]:
                break
            chunk = os.read(fd, 65536)
            if not chunk:
                raise RuntimeError("exit")
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("id") == 2:
                    if "error" in msg:
                        raise RuntimeError("rpc")
                    return
        raise subprocess.TimeoutExpired("codex app-server", TIMEOUT_SECONDS)
    finally:
        try:
            proc.stdin.close()  # o app-server sai sozinho; da tempo de terminar a escrita do auth.json
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
            proc.wait()
        proc.stdout.close()


# Gancho por provedor: Gemini (#60) entra aqui.
RENEWERS: dict[str, Callable[[Path], None]] = {
    "claude": lambda profile: _run("claude", ["auth", "status"], "CLAUDE_CONFIG_DIR", profile),
    "codex": _codex_refresh,
}
_PROFILE_KEYS = {"claude": "claude_dir", "codex": "codex_dir"}


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
