"""Renovacao de Contas inativas antes da consulta (Spec 08).

A CLI da ferramenta, executada no Perfil Isolado, renova o token vencido. No maximo uma vez
por Conta por Intervalo de Atualizacao (estado em refresh_state.json). Falhas sao isoladas por
Conta e registradas so como classe (`cli_missing`, `timeout`, `failed`), nunca com saida da CLI.
"""

from __future__ import annotations

import base64
import json
import mmap
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
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


class RenewError(Exception):
    """Falha de renovacao ja classificada; `code` e a unica coisa que vai para o estado e o stderr."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- Gemini (Spec 08, ticket 60) -------------------------------------------------------------
# Renova o access_token da Conta inativa com o refresh_token da copia isolada (POST
# grant_type=refresh_token). O client_id vem do `aud` do id_token das proprias credenciais. O Google
# exige client_secret do MESMO app OAuth; o das credenciais e o da Antigravity. Em vez de embutir o
# segredo no repositorio (app de terceiro, repositorio publico), ele e lido EM TEMPO DE EXECUCAO do
# binario da Antigravity instalado na maquina do usuario: candidatos `GOCSPX-` + 28 caracteres, o
# par certo e o que o Google aceita (invalid_client -> proximo candidato). O segredo fica so em
# memoria durante a chamada: nunca em log, erro, estado, status.json nem argumento de processo.
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
HTTP_TIMEOUT_SECONDS = 10
MAX_SECRET_CANDIDATES = 8
_CLIENT_ID_RE = re.compile(r"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com")
_SECRET_RE = re.compile(rb"GOCSPX-[A-Za-z0-9_-]{28}")


def _agy_binary() -> Path:
    exe = shutil.which("agy") or "~/.local/bin/agy"  # testes substituem
    path = Path(exe).expanduser().resolve()
    if not path.is_file():
        raise RenewError("binary_missing")
    return path


def _client_id_from(creds: dict[str, Any]) -> str:
    try:
        payload = str(creds["id_token"]).split(".")[1]
        aud = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["aud"]
    except Exception:
        raise RenewError("client_id_missing") from None
    if not isinstance(aud, str) or not _CLIENT_ID_RE.fullmatch(aud):
        raise RenewError("client_id_missing")
    return aud


def _secret_candidates(binary: Path, client_id: str) -> list[str]:
    """Ate MAX_SECRET_CANDIDATES segredos candidatos do binario, se ele contem o client_id."""
    try:
        with open(binary, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            if mm.find(client_id.encode()) < 0:
                raise RenewError("client_id_not_in_binary")
            found: dict[str, None] = {}
            for m in _SECRET_RE.finditer(mm):
                found[m.group().decode()] = None
                if len(found) >= MAX_SECRET_CANDIDATES:
                    break
    except RenewError:
        raise
    except (OSError, ValueError):  # ValueError: arquivo vazio nao pode ser mapeado
        raise RenewError("binary_unreadable") from None
    if not found:
        raise RenewError("no_secret_candidates")
    return list(found)


def _post_refresh(client_id: str, secret: str, refresh_token: str) -> dict[str, Any]:
    """Um POST de renovacao. Devolve a resposta; erro vira RenewError (invalid_client = tentar outro)."""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": refresh_token,
        "client_id": client_id, "client_secret": secret,
    }).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with refresh.NO_REDIRECT_OPENER.open(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read(100_000)).get("error")
        except Exception:
            err = None
        if err == "invalid_grant":
            raise RenewError("revoked") from None
        if err == "invalid_client" or exc.code == 401:
            raise RenewError("invalid_client") from None
        raise RenewError("failed") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise RenewError("network") from None
    except ValueError:
        raise RenewError("invalid_response") from None
    token, ttl = (data.get("access_token"), data.get("expires_in")) if isinstance(data, dict) else (None, None)
    if not isinstance(token, str) or not token or isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
        raise RenewError("invalid_response")
    return data


def _write_private_atomic(path: Path, data: dict[str, Any]) -> None:
    """Temporario 0600 no mesmo diretorio + os.replace. Nao segue symlink: o alvo e sempre o arquivo do perfil."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".oauth_", suffix=".tmp")  # mkstemp ja cria 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _gemini_refresh(profile: Path) -> None:
    cred = profile / "oauth_creds.json"
    if cred.is_symlink():
        raise RenewError("failed")  # nunca escrever por um link para fora do Perfil Isolado
    try:
        creds = json.loads(cred.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RenewError("failed") from None
    refresh_token = creds.get("refresh_token") if isinstance(creds, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RenewError("revoked")
    client_id = _client_id_from(creds)
    candidates = _secret_candidates(_agy_binary(), client_id)
    for secret in candidates:
        try:
            data = _post_refresh(client_id, secret, refresh_token)
            break
        except RenewError as exc:
            if exc.code != "invalid_client":
                raise
    else:
        raise RenewError("no_valid_secret")
    del candidates, secret
    expires_in = int(data["expires_in"])
    creds["access_token"] = data["access_token"]
    creds["expires_in"] = expires_in
    creds["expiry"] = (refresh.utcnow() + timedelta(seconds=expires_in)).isoformat()
    creds.pop("expiry_date", None)  # leitores preferem expiry_date (ms); o antigo faria o token novo parecer vencido
    for key in ("id_token", "refresh_token", "token_type"):  # refresh_token so se o Google rotacionar
        if isinstance(data.get(key), str) and data[key]:
            creds[key] = data[key]
    _write_private_atomic(cred, creds)


# Gancho por provedor
RENEWERS: dict[str, Callable[[Path], None]] = {
    "claude": lambda profile: _run("claude", ["auth", "status"], "CLAUDE_CONFIG_DIR", profile),
    "codex": _codex_refresh,
    "gemini": _gemini_refresh,
}
_PROFILE_KEYS = {"claude": "claude_dir", "codex": "codex_dir", "gemini": "gemini_dir"}


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
    except RenewError as exc:
        error = exc.code
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
