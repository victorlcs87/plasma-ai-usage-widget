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
import signal
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
from ai_usage_collector.capture import (
    _CREDENTIAL_FILENAMES,
    _extract_credential_signature,
    _read_json_dict,
    _store_into_profile,
    _system_identity,
    get_active_credentials,
    get_profiles_base_dir,
    get_system_credential_file,
)
from ai_usage_collector.config import config_lock, load_config
from ai_usage_collector.discovery import parse_timestamp
from ai_usage_collector.identity import _jwt_claims, credential_identity

TIMEOUT_SECONDS = 20
BUDGET_SECONDS = 45  # orcamento total de renovacao por ciclo (as renovacoes sao seriais dentro do lock)
EXPIRY_MARGIN_SECONDS = 300
MAX_READ_BYTES = 1_000_000
MAX_BINARY_BYTES = 1 << 30
_clock = time.monotonic  # testes substituem

# O filho (claude/codex) recebe so o necessario: nunca ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN,
# OPENAI_API_KEY, CODEX_API_KEY nem qualquer outro segredo do ambiente do Coletor.
_ENV_KEEP = ("PATH", "HOME", "LANG", "TMPDIR")
_ENV_PREFIXES = ("LC_", "XDG_")


def _child_env(env_name: str, profile: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_KEEP or k.startswith(_ENV_PREFIXES)}
    env[env_name] = str(profile)
    return env


def _kill_group(proc: subprocess.Popen) -> None:
    """Mata o grupo do filho (start_new_session): netos da CLI nao ficam orfaos."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def _find_cli(binary: str) -> str | None:
    """Prefer PATH; Plasma may omit the user's native CLI installation directory."""
    exe = shutil.which(binary)
    if exe:
        return exe
    return shutil.which(str(Path.home() / ".local" / "bin" / binary))


def _run(binary: str, args: list[str], env_name: str, profile: Path) -> None:
    exe = _find_cli(binary)
    if not exe:
        raise FileNotFoundError(binary)
    # Lista de argumentos, sem shell; saida descartada (pode conter dados da Conta)
    proc = subprocess.Popen(
        [exe, *args], env=_child_env(env_name, profile), start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        code = proc.wait(timeout=TIMEOUT_SECONDS)
    except BaseException:
        _kill_group(proc)
        proc.wait()
        raise
    if code != 0:
        raise RuntimeError("exit")


def _codex_refresh(profile: Path) -> None:
    """Pede ao app-server do Codex (CODEX_HOME = Perfil Isolado) `account/read` com refreshToken.

    Teste real (22/10/2026, copia de perfil com id_token vencido): `codex login status`, `doctor`
    e `debug models` NAO renovam o token; so o JSON-RPC `account/read {refreshToken: true}` do
    `codex app-server` renova (reescreve auth.json, sem gastar tokens de modelo). O app-server
    sai ao fechar o stdin, entao o processo fica aberto ate a resposta (id 2) ou o timeout.
    """
    exe = _find_cli("codex")
    if not exe:
        raise FileNotFoundError("codex")
    proc = subprocess.Popen(
        [exe, "app-server", "--listen", "stdio://"], env=_child_env("CODEX_HOME", profile), start_new_session=True,
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
            if len(buf) > MAX_READ_BYTES:
                raise RenewError("failed")
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
            _kill_group(proc)
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
    try:
        if path.stat().st_size > MAX_BINARY_BYTES:
            raise RenewError("binary_unreadable")
    except OSError:
        raise RenewError("binary_unreadable") from None
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
            data = json.loads(resp.read(MAX_READ_BYTES))
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
    for old in path.parent.glob(".oauth_*.tmp"):  # sobras de uma queda no meio da gravacao
        try:
            if time.time() - old.stat().st_mtime > 3600:
                old.unlink()
        except OSError:
            pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".oauth_", suffix=".tmp")  # mkstemp ja cria 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
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
    _write_private_atomic(cred, _refresh_gemini_credentials(creds))


def _refresh_gemini_credentials(creds: dict[str, Any]) -> dict[str, Any]:
    creds = dict(creds)
    refresh_token = creds.get("refresh_token") if isinstance(creds, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RenewError("revoked")
    client_id = _client_id_from(creds)
    candidates = _secret_candidates(_agy_binary(), client_id)
    started = _clock()
    for secret in candidates:
        if _clock() - started > TIMEOUT_SECONDS:  # teto total do Gemini (orcamento do ciclo)
            raise RenewError("timeout")
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
    return creds


# Gancho por provedor
RENEWERS: dict[str, Callable[[Path], None]] = {
    "claude": lambda profile: _run("claude", ["auth", "status"], "CLAUDE_CONFIG_DIR", profile),
    "codex": _codex_refresh,
    "gemini": _gemini_refresh,
}
_PROFILE_KEYS = {"claude": "claude_dir", "codex": "codex_dir", "gemini": "gemini_dir"}


def _expiry_ts(provider: str, cred_file: Path) -> float | None:
    """Validade (epoch s) do access token do Perfil, lida sem rede; None se desconhecida."""
    creds = _read_json_dict(cred_file)
    if not creds:
        return None
    if provider == "claude":
        oauth = creds.get("claudeAiOauth")
        return parse_timestamp(oauth.get("expiresAt")) if isinstance(oauth, dict) else None
    if provider == "codex":
        tokens = creds.get("tokens") if isinstance(creds.get("tokens"), dict) else creds
        exp = _jwt_claims(tokens.get("access_token")).get("exp")  # so o payload; a assinatura nao importa aqui
        return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp > 0 else None
    ts = parse_timestamp(creds.get("expiry_date") or creds.get("expiry"))
    if ts is None:
        ttl = creds.get("expires_in")
        if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) and ttl > 0:
            try:
                ts = cred_file.stat().st_mtime + ttl
            except OSError:
                return None
    return ts


def needs_renewal(provider: str, cred_file: Path, now_ts: float, interval: int) -> bool:
    """True se o access token venceu ou vence antes do proximo Intervalo de Atualizacao (+ margem)."""
    exp = _expiry_ts(provider, cred_file)
    return exp is None or exp <= now_ts + interval + EXPIRY_MARGIN_SECONDS


def _skip_reason(
    cyc: refresh.RefreshCycle, provider: str, profile: Path, cred_file: Path, override: Path | None,
    config_path: str | Path | None,
) -> str | None:
    """Codigo de 'pulado' se renovar esta pasta pudesse tocar a Conta Ativa ou algo fora dos Perfis Isolados.

    Fail-closed: qualquer duvida (leitura falhou, identidade desconhecida) pula. So codigos, nunca segredos.
    """
    try:
        base = get_profiles_base_dir(config_path).resolve()
        if profile == base or not profile.is_relative_to(base):
            return "outside_profiles"
        if cred_file.is_symlink():
            return "symlink"
        fixed = {Path(f"~/{d}").expanduser().resolve() for d in (".claude", ".codex", ".gemini")}
        sys_file = get_system_credential_file(provider, override)
        if profile in fixed or sys_file.resolve().parent == profile or cred_file.resolve() == sys_file.resolve():
            return "system_dir"
        sys_creds = cyc.system_creds.get(provider, False)
        if sys_creds is False:
            sys_creds = cyc.system_creds[provider] = get_active_credentials(provider, override)
        if sys_creds is None:
            # Sem credencial legivel: so segue se tambem nao ha arquivo de sistema (senao e leitura falha)
            from ai_usage_collector.capture import _ANTIGRAVITY_TOKEN, _gemini_base  # noqa: PLC0415

            extra = [_gemini_base() / _ANTIGRAVITY_TOKEN] if provider == "gemini" and not override else []
            # ponytail: chaveiro do Gemini (secret-tool) nao e verificavel aqui; se falhar e nao houver arquivo, segue
            return "detection_failed" if any(os.path.lexists(f) for f in [sys_file, *extra]) else None
        mine = _extract_credential_signature(provider, _read_json_dict(cred_file))
        theirs = _extract_credential_signature(provider, sys_creds)
        for key in ("refresh_token", "access_token"):
            if mine.get(key) and mine[key] == theirs.get(key):
                return "same_credential"
        ident_sys = _system_identity(provider, sys_creds, sys_file)
        ident_mine = credential_identity(provider, cred_file)
        if ident_sys is None or ident_mine is None:
            return "identity_unknown"
        if ident_sys.key == ident_mine.key:
            return "same_identity"
    except Exception:
        return "detection_failed"
    return None


def renew_gemini_enabled(config: Any) -> bool:
    """Opt-in: so um `renew.gemini` booleano True liga (padrao desligada; usa o app OAuth da Antigravity)."""
    raw = config.get("renew") if isinstance(config, dict) else None
    return isinstance(raw, dict) and raw.get("gemini") is True


def renew_inactive(
    cyc: refresh.RefreshCycle, provider: str, account_id: str, account: dict[str, Any],
    interval: int, override: Path | None = None, force: bool = False,
    config_path: str | Path | None = None, manual: bool = False,
) -> str | None:
    """Renova o Perfil Isolado da Conta se devido; devolve a classe do erro (None = ok ou nada a fazer).

    `force` ("Atualizar agora") passa por cima do limite de uma tentativa por Intervalo, mas nunca das
    regras de seguranca, da validade do token nem do orcamento do ciclo.
    """
    renewer = RENEWERS.get(provider)
    raw_dir = account.get(_PROFILE_KEYS.get(provider, ""))
    if manual and not raw_dir:
        raw_file = account.get("credential_path") or account.get("credentials_path")
        if raw_file and Path(raw_file).name == _CREDENTIAL_FILENAMES.get(provider):
            raw_dir = str(Path(raw_file).expanduser().parent)
    if not renewer or not raw_dir:
        if manual:
            cyc.record_renewal(provider, account_id, "cli_missing" if not renewer else "detection_failed")
        return None
    if not (manual or force or cyc.renewal_due(provider, account_id, interval)):
        return None
    if provider == "gemini" and not manual and not renew_gemini_enabled(load_config(config_path)):
        return None  # desligada: nem 'which agy', nem leitura do binario, nem rede
    who = repr(f"{provider}:{account_id}")
    profile = Path(raw_dir).expanduser().resolve()
    cred_file = profile / _CREDENTIAL_FILENAMES[provider]
    if reason := _skip_reason(cyc, provider, profile, cred_file, override, config_path):
        sys.stderr.write(f"Aviso: renovacao da Conta {who} pulada ({reason})\n")
        if manual:
            cyc.record_renewal(provider, account_id, "detection_failed")
        return None
    if not manual and not needs_renewal(provider, cred_file, cyc.now.timestamp(), interval):
        return None
    elapsed = 0.0 if cyc.renew_started is None else _clock() - cyc.renew_started
    if elapsed > BUDGET_SECONDS - TIMEOUT_SECONDS:  # adiada ao proximo ciclo; nao e falha nem consome o Intervalo
        return None
    if cyc.renew_started is None:
        cyc.renew_started = _clock()
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
        sys.stderr.write(f"Aviso: renovacao da Conta {who} falhou ({error})\n")
    return error



def _renew_active_manual(
    cyc: refresh.RefreshCycle, provider: str, account_id: str, account: dict[str, Any],
    override: Path | None = None, config_path: str | Path | None = None,
) -> None:
    """Explicit renewal of the system account, only while its CLI is definitely stopped.

    Refresh through the provider's own CLI (Gemini uses the existing OAuth route),
    then synchronize the renewed credential into its isolated copy. No account switch.
    """
    from ai_usage_collector.running import detect_running
    from ai_usage_collector.capture import get_active_gemini_credentials, _store_gemini_keyring

    error = None
    try:
        running = detect_running().get(provider)
        if running is not False:
            raise RenewError("cli_running" if running else "detection_failed")
        raw_path = account.get("credential_path") or account.get("credentials_path")
        if not raw_path:
            raise RenewError("detection_failed")
        copy = Path(raw_path).expanduser()
        base = get_profiles_base_dir(config_path).resolve()
        system = get_system_credential_file(provider, override)
        direct_system = copy.absolute() == system.absolute()
        if copy.is_symlink() or (not direct_system and not copy.resolve().is_relative_to(base)):
            raise RenewError("detection_failed")
        creds = get_active_credentials(provider, override)
        current = _system_identity(provider, creds, system) if creds else None
        expected = credential_identity(provider, copy)
        if not current or not expected or current.key != expected.key:
            raise RenewError("detection_failed")
        if provider == "gemini":
            live, source = get_active_gemini_credentials(override)
            if not live:
                raise RenewError("revoked")
            if isinstance(live.get("token"), dict):
                live = {**{k: v for k, v in live.items() if k != "token"}, **live["token"]}
            if source != "keyring (secret-tool)":
                source_path = Path(source)
                if source_path.is_symlink() or not source_path.is_file():
                    raise RenewError("detection_failed")
            updated = _refresh_gemini_credentials(live)
            if source == "keyring (secret-tool)":
                _store_gemini_keyring(updated)
            else:
                source_path = Path(source)
                if source_path.is_symlink():
                    raise RenewError("detection_failed")
                original = _read_json_dict(source_path)
                if not original:
                    raise RenewError("detection_failed")
                if isinstance(original.get("token"), dict):
                    token_keys = {"access_token", "refresh_token", "token_type", "expires_in", "expiry", "id_token", "scope"}
                    nested = {**original["token"], **{k: v for k, v in updated.items() if k in token_keys}}
                    nested.pop("expiry_date", None)
                    updated_file = {**original, "token": nested}
                    if "id_token" in original:
                        updated_file["id_token"] = updated.get("id_token", original["id_token"])
                else:
                    updated_file = updated
                _write_private_atomic(source_path, updated_file)
        else:
            if system.is_symlink() or system.name != _CREDENTIAL_FILENAMES[provider]:
                raise RenewError("detection_failed")
            renewer = RENEWERS.get(provider)
            if not renewer:
                raise RenewError("cli_missing")
            renewer(system.parent)
            updated = get_active_credentials(provider, override)
            if not updated:
                raise RenewError("failed")
        # Fail closed if the CLI unexpectedly switched identity.
        identity = _system_identity(provider, updated, system)
        if not identity or identity.key != expected.key:
            raise RenewError("detection_failed")
        if not direct_system:
            if provider in ("claude", "codex"):
                _store_into_profile(provider, updated, system, copy)
            else:
                _write_private_atomic(copy, updated)
        cyc.system_creds[provider] = updated
    except RenewError as exc:
        error = exc.code
    except FileNotFoundError:
        error = "cli_missing"
    except subprocess.TimeoutExpired:
        error = "timeout"
    except Exception:
        error = "failed"
    cyc.record_renewal(provider, account_id, error)


def renew_active_manual(
    cyc: refresh.RefreshCycle, provider: str, account_id: str, account: dict[str, Any],
    override: Path | None = None, config_path: str | Path | None = None,
) -> None:
    # Serialize writes against account switching/capture, then re-check identity inside the lock.
    with config_lock(config_path):
        _renew_active_manual(cyc, provider, account_id, account, override, config_path)


def renew_active_auto(
    cyc: refresh.RefreshCycle, provider: str, account_id: str, account: dict[str, Any],
    interval: int, override: Path | None = None, config_path: str | Path | None = None,
) -> bool:
    """Tenta uma renovação automática segura; True somente após sucesso."""
    if not cyc.renewal_due(provider, account_id, interval):
        return False
    elapsed = 0.0 if cyc.renew_started is None else _clock() - cyc.renew_started
    if elapsed > BUDGET_SECONDS - TIMEOUT_SECONDS:
        return False
    if cyc.renew_started is None:
        cyc.renew_started = _clock()
    renew_active_manual(cyc, provider, account_id, account, override, config_path)
    return cyc.renewals[f"{provider}:{account_id}"]["error"] is None
