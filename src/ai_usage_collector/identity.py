"""Identidade da Conta por provedor (ADR-0008).

Interface unica para responder "qual e a identidade desta credencial?". Cada provedor
registra um adaptador em `_ADAPTERS`; Codex e Gemini entram depois (tickets 19 e 20)
apenas adicionando o seu adaptador, sem alterar quem consome esta interface.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, NamedTuple


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


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json_atomic(data: dict[str, Any], path: Path, mode: int = 0o600) -> None:
    """Grava JSON atomicamente sem alterar as permissoes do diretorio pai (ex.: $HOME)."""
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


# --- Claude ------------------------------------------------------------------
# O .credentials.json nao traz email nem accountId; o Claude Code guarda a conta em
# `oauthAccount` do arquivo de estado: ~/.claude.json para o diretorio padrao ~/.claude,
# ou $CLAUDE_CONFIG_DIR/.claude.json (vale tambem para os Perfis Isolados).


def _claude_state_file(cred_file: Path) -> Path:
    config_dir = cred_file.expanduser().resolve().parent
    if config_dir == Path("~/.claude").expanduser().resolve():
        return Path("~/.claude.json").expanduser()
    return config_dir / ".claude.json"


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
    oauth = _load_json(_claude_state_file(src_cred_file)).get("oauthAccount")
    dst = _claude_state_file(dst_cred_file)
    if not dst.exists() and not isinstance(oauth, dict):
        return
    data = _load_json(dst)  # preserva as demais chaves do estado do Claude Code
    if isinstance(oauth, dict):
        data["oauthAccount"] = oauth
    else:
        # Sem identidade na origem: nao deixar a identidade antiga no destino.
        data.pop("oauthAccount", None)
    write_json_atomic(data, dst)


_ADAPTERS: dict[str, _Adapter] = {
    "claude": _Adapter(read=_claude_read, state_file=_claude_state_file, copy_state=_claude_copy_state),
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


def identity_state_file(provider: str, cred_file: str | Path) -> Path | None:
    adapter = _ADAPTERS.get(provider.lower().strip())
    return adapter.state_file(Path(cred_file)) if adapter else None


def copy_identity_state(provider: str, src_cred_file: str | Path, dst_cred_file: str | Path) -> None:
    adapter = _ADAPTERS.get(provider.lower().strip())
    if adapter:
        adapter.copy_state(Path(src_cred_file), Path(dst_cred_file))
