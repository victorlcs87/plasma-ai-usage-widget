"""Identidade da Conta por provedor (ADR-0008).

Interface unica para responder "qual e a identidade desta credencial?". Cada provedor
registra um adaptador em `_ADAPTERS`; o Codex entra depois (ticket 19)
apenas adicionando o seu adaptador, sem alterar quem consome esta interface.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, NamedTuple

from ai_usage_collector.discovery import extract_jwt_identity


class Identity(NamedTuple):
    key: str  # identificador estavel usado na comparacao
    email: str | None  # forma legivel para rotulos


@dataclass(frozen=True)
class _Adapter:
    # Identidade da credencial armazenada em `cred_file`.
    read: Callable[[Path], Identity | None]
    # Arquivo de estado com os metadados de identidade que acompanha `cred_file` (ou None).
    state_file: Callable[[Path], Path | None]
    # Copia os metadados de identidade de `src_cred_file` para junto de `dst_cred_file`.
    copy_state: Callable[[Path, Path], None]
    # Identidade de credenciais ja em memoria (ex.: chaveiro, que prevalece sobre o arquivo).
    from_creds: Callable[[dict[str, Any]], Identity | None] | None = None


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_json_strict(path: Path) -> dict[str, Any]:
    """Le um arquivo de estado existente; erro se ilegivel (nunca sobrescrever estado corrompido)."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Arquivo de estado '{path}' não contém um objeto JSON.")
    return data


def write_json_atomic(data: dict[str, Any], path: Path, mode: int = 0o600) -> None:
    """Grava JSON atomicamente no alvo real (preserva symlinks) sem alterar as permissoes do
    diretorio pai (ex.: $HOME). Rele o arquivo apos gravar: se outro processo o regravou no
    intervalo, lanca erro para o chamador acionar o rollback.
    """
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".identity_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    if _load_json(path) != data:
        raise RuntimeError(f"Arquivo '{path}' foi alterado por outro processo durante a gravação.")


# --- Claude ------------------------------------------------------------------
# O .credentials.json nao traz email nem accountId; o Claude Code guarda a conta em
# `oauthAccount` do arquivo de estado: ~/.claude.json para o diretorio padrao ~/.claude,
# ou $CLAUDE_CONFIG_DIR/.claude.json (vale tambem para os Perfis Isolados).


def _claude_state_file(cred_file: Path) -> Path:
    config_dir = cred_file.expanduser().absolute().parent.resolve()
    if config_dir == Path("~/.claude").expanduser().resolve():
        return Path("~/.claude.json").expanduser().resolve()
    return (config_dir / ".claude.json").resolve()


def _claude_read(cred_file: Path) -> Identity | None:
    oauth = _load_json(_claude_state_file(cred_file)).get("oauthAccount")
    if not isinstance(oauth, dict):
        return None
    uuid = str(oauth.get("accountUuid") or "").strip()
    email = str(oauth.get("emailAddress") or "").strip() or None
    if uuid:
        return Identity(uuid.lower(), email)
    if email:
        return Identity(f"email:{email.lower()}", email)
    return None


def _claude_copy_state(src_cred_file: Path, dst_cred_file: Path) -> None:
    oauth = _load_json_strict(_claude_state_file(src_cred_file)).get("oauthAccount")
    dst = _claude_state_file(dst_cred_file)
    if not dst.exists() and not isinstance(oauth, dict):
        return
    data = _load_json_strict(dst)  # preserva as demais chaves do estado do Claude Code
    if isinstance(oauth, dict):
        data["oauthAccount"] = oauth
    else:
        # Sem identidade na origem: nao deixar a identidade antiga no destino.
        data.pop("oauthAccount", None)
    write_json_atomic(data, dst)


# --- Gemini ------------------------------------------------------------------
# A identidade e o email Google da conta, no proprio `id_token` da credencial (arquivo
# oauth_creds.json ou payload do chaveiro, plano ou aninhado em `token`); nao ha arquivo de estado.


def _gemini_from_creds(creds: dict[str, Any]) -> Identity | None:
    tok = creds.get("token") if isinstance(creds.get("token"), dict) else {}
    email = str(creds.get("email") or "").strip()
    if not email:
        found = extract_jwt_identity(creds.get("id_token") or tok.get("id_token"))
        email = found if found and "@" in found else ""  # `sub` nao e email
    return Identity(f"email:{email.lower()}", email) if email else None


def _gemini_read(cred_file: Path) -> Identity | None:
    return _gemini_from_creds(_load_json(cred_file))


_ADAPTERS: dict[str, _Adapter] = {
    "claude": _Adapter(read=_claude_read, state_file=_claude_state_file, copy_state=_claude_copy_state),
    "gemini": _Adapter(
        read=_gemini_read,
        state_file=lambda cred_file: None,
        copy_state=lambda src, dst: None,
        from_creds=_gemini_from_creds,
    ),
}


def supports_identity(provider: str) -> bool:
    return provider.lower().strip() in _ADAPTERS


def credential_identity(provider: str, cred_file: str | Path | None) -> Identity | None:
    """Identidade da Conta da credencial em `cred_file`, ou None se desconhecida."""
    adapter = _ADAPTERS.get(provider.lower().strip())
    if adapter is None or cred_file is None:
        return None
    try:
        return adapter.read(Path(cred_file))
    except Exception:
        return None


def creds_identity(provider: str, creds: dict[str, Any] | None) -> Identity | None:
    """Identidade de credenciais ja lidas (ex.: do chaveiro), ou None se o provedor nao a traz nelas."""
    adapter = _ADAPTERS.get(provider.lower().strip())
    if adapter is None or adapter.from_creds is None or not creds:
        return None
    try:
        return adapter.from_creds(creds)
    except Exception:
        return None


def identity_state_file(provider: str, cred_file: str | Path) -> Path | None:
    adapter = _ADAPTERS.get(provider.lower().strip())
    return adapter.state_file(Path(cred_file)) if adapter else None


def copy_identity_state(provider: str, src_cred_file: str | Path, dst_cred_file: str | Path) -> None:
    adapter = _ADAPTERS.get(provider.lower().strip())
    if adapter:
        adapter.copy_state(Path(src_cred_file), Path(dst_cred_file))
