"""Instala e remove o `notify` do Estado da Sessao no config.toml do Codex (ADR-0009, ticket 36).

Sem escritor de TOML na stdlib, a edicao e textual e minima: uma unica linha nossa, no topo do
arquivo (chave de nivel raiz), reconhecida por um marcador no fim. O resto do arquivo nunca e
reserializado. Antes de gravar, o resultado e relido com `tomllib` e precisa ser igual ao original
mais/menos a chave `notify`; senao nada e alterado. Um `notify` do usuario nunca e sobrescrito.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ai_usage_collector import session_state
from ai_usage_collector.claude_hooks import HooksError, edit_bytes

MARKER = "# plasma-ai-usage:codex-notify"
_OURS = re.compile(r"^notify = \[.*\] " + re.escape(MARKER) + r"$")


def notify_line(state_dir: Path, codex_home: Path) -> str:
    """Argv executado pelo Codex SEM shell: um array TOML (strings JSON sao strings TOML basicas
    validas), com caminhos absolutos e nenhum dado externo; o Codex anexa o JSON do evento.
    """
    script = Path(session_state.__file__).resolve()
    argv = [sys.executable, "-I", str(script), session_state.CODEX_NOTIFY_FLAG, str(state_dir), str(codex_home)]
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for a in argv for c in a):
        raise HooksError("Caminho com caractere de controle, DEL ou inválido (surrogate); nada foi alterado.")
    return f"notify = {json.dumps(argv, ensure_ascii=True)} {MARKER}"


def config_path() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env and not Path(env).expanduser().is_absolute():
        raise HooksError("CODEX_HOME deve ser um caminho absoluto para instalar o notify.")
    return session_state.codex_home_dir() / "config.toml"


def _tomllib():
    try:
        import tomllib
    except ImportError:  # Python 3.10
        raise HooksError("O notify do Codex exige Python 3.11 ou mais novo (tomllib); nada foi alterado.")
    return tomllib


def _toml(raw: bytes, real: Path, backup: bool = True) -> dict[str, Any]:
    try:
        return _tomllib().loads(raw.decode("utf-8"))
    except ValueError as e:  # TOMLDecodeError e UnicodeDecodeError
        from ai_usage_collector.claude_hooks import _backup

        bak = f" Backup em {_backup(real, raw)}." if backup else ""
        raise HooksError(f"{real} não é um TOML válido ({e}); nada foi alterado.{bak}")


def _check(new: str, old_data: dict[str, Any], expect_notify: Any, real: Path) -> bytes:
    """Garante que so a chave `notify` mudou (protege de marcador dentro de string multilinha etc.)."""
    expected = {k: v for k, v in old_data.items() if k != "notify"}
    if expect_notify is not None:
        expected["notify"] = expect_notify
    if _toml(new.encode("utf-8"), real, backup=False) != expected:
        raise HooksError(f"A edição de {real} alteraria mais do que o notify; nada foi alterado.")
    return new.encode("utf-8")


def _transform(line: str | None):
    """`line` = nossa linha desejada (instalar) ou None (remover)."""

    def run(raw: bytes, real: Path) -> bytes | None:
        data = _toml(raw, real)
        text = raw.decode("utf-8")
        lines = text.splitlines(keepends=True)
        ours = [i for i, ln in enumerate(lines) if _OURS.match(ln.rstrip("\r\n"))]
        for i in ours:  # a linha precisa ser o `notify` de RAIZ, nao uma chave igual dentro de uma tabela
            if _tomllib().loads(lines[i]).get("notify") != data.get("notify"):
                raise HooksError(f"Uma linha do widget em {real} está dentro de uma tabela, não na raiz; nada foi alterado.")
        if line is not None and "notify" in data and not ours:
            raise HooksError(f"{real} já tem um `notify` seu; não foi sobrescrito. Remova-o ou encadeie-o manualmente.")
        if line is None and not ours:
            return None
        rest = [ln for i, ln in enumerate(lines) if i not in ours]
        if line is None:
            return _check("".join(rest), data, None, real)
        if len(ours) == 1 and lines[ours[0]].rstrip("\r\n") == line:
            return None
        # nossa linha vai ao topo (chave de nivel raiz); duplicatas nossas somem
        return _check(line + "\n" + "".join(rest), data, json.loads(line[len("notify = "):-len(MARKER) - 1]), real)

    return run


def install_notify(state_dir: Path, config: Path | None = None) -> str:
    _tomllib()  # antes de criar qualquer diretorio ou arquivo
    config = config or config_path()
    line = notify_line(state_dir, config.parent.resolve())
    changed = edit_bytes(config, _transform(line), creates=True)
    return f"Notify do Estado da Sessão do Codex {'instalado' if changed else 'já estava instalado'} em {config}."


def uninstall_notify(config: Path | None = None) -> str:
    config = config or config_path()
    if edit_bytes(config, _transform(None), creates=False):
        return f"Notify do Estado da Sessão do Codex removido de {config}."
    return f"Nenhum notify do widget em {config}."
