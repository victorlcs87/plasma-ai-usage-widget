"""Verificacao de atualizacao (ticket 39): widget (GitHub Releases) e CLIs (npm), no maximo 1x/dia por fonte.

Somente leitura e sem credenciais: hosts fixos (api.github.com, registry.npmjs.org) por https, sem
redirect, sem cookies/token, timeout curto e resposta limitada. Nada e baixado, instalado ou executado
(so `<cli> --version`, sem shell). Texto vindo da rede e nao confiavel: so a versao reconstruida pelo
parser e a URL da release (validada) chegam ao status.json. Qualquer falha e silenciosa.

Estado em `update_check.json` ao lado do status.json (0600, escrita atomica), por fonte:
checked_at/latest/url/local. Falha de rede tambem consome o dia (sem rajada); a ultima versao
conhecida e mantida. Roda dentro do ciclo de coleta, sob o lock do status.json.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_usage_collector import __version__
from ai_usage_collector.config import save_secure_json
from ai_usage_collector.extractors.claude import _NO_REDIRECT  # opener que nunca segue redirect

STATE_FILENAME = "update_check.json"
INTERVAL_SECONDS = 86400
TIMEOUT = 3.0
VERSION_TIMEOUT = 3.0
MAX_BYTES = 256 * 1024

_REPO = "victorlcs87/plasma-ai-usage-widget"
_RELEASE_URL = re.compile(rf"https://github\.com/{re.escape(_REPO)}/[A-Za-z0-9._~/%+-]{{0,200}}")
# fonte -> (URL fixa, chave da versao na resposta, nome esperado no npm)
SOURCES: dict[str, tuple[str, str, str | None]] = {
    "widget": (f"https://api.github.com/repos/{_REPO}/releases/latest", "tag_name", None),
    "claude": ("https://registry.npmjs.org/@anthropic-ai/claude-code/latest", "version", "@anthropic-ai/claude-code"),
    "codex": ("https://registry.npmjs.org/@openai/codex/latest", "version", "@openai/codex"),
    "gemini": ("https://registry.npmjs.org/@google/gemini-cli/latest", "version", "@google/gemini-cli"),
}
_OPENER = _NO_REDIRECT  # testes substituem

_SEMVER = re.compile(r"v?(\d{1,9})\.(\d{1,9})\.(\d{1,9})(?:-([0-9A-Za-z][0-9A-Za-z.-]{0,30}))?(?:\+[0-9A-Za-z.-]{1,30})?")


def parse_version(text: Any, search: bool = False) -> tuple[str, tuple] | None:
    """(versao canonica, chave de ordenacao) de um semver tolerante ('v', pre-release, build); None se lixo.

    `search` procura o semver dentro de um texto maior (saida de `--version`)."""
    if not isinstance(text, str) or len(text) > 200:
        return None
    m = (_SEMVER.search if search else _SEMVER.fullmatch)(text.strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    core = tuple(int(x) for x in (major, minor, patch))
    # pre-release < release; ids numericos < alfanumericos (semver 2.0)
    pre_key = tuple((0, int(i), "") if i.isdigit() else (1, 0, i) for i in pre.split(".")) if pre else ()
    canonical = ".".join(map(str, core)) + (f"-{pre}" if pre else "")
    return canonical, (*core, pre is None, pre_key)


def is_newer(latest: str | None, current: str | None) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a[1] > b[1])


def update_check_enabled(config: Any) -> bool:
    """Padrao ligado (spec 05, historia 72); so um booleano valido em `updates.check` desliga."""
    raw = config.get("updates") if isinstance(config, dict) else None
    check = raw.get("check") if isinstance(raw, dict) else None
    return check if isinstance(check, bool) else True


def _get_json(url: str) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "plasma-ai-usage-widget"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            return None
        data = json.loads(body)
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _fetch_latest(source: str) -> tuple[str, str | None] | None:
    """(versao canonica, URL da release validada ou None) ou None se a resposta e invalida."""
    url, key, package = SOURCES[source]
    data = _get_json(url)
    parsed = parse_version(data.get(key)) if data else None
    if not data or not parsed or (package and data.get("name") != package):
        return None
    return parsed[0], _release_url(data.get("html_url")) if source == "widget" else None


def _release_url(value: Any) -> str | None:
    return value if isinstance(value, str) and _RELEASE_URL.fullmatch(value) else None


def local_version(binary: str) -> str | None:
    """Versao do CLI instalado via `<binario> --version` (lista de args, sem shell, timeout curto); None se falhar."""
    path = shutil.which(binary)
    if not path or not os.path.isabs(path):
        return None
    try:
        run = subprocess.run([path, "--version"], capture_output=True, text=True, errors="replace",
                             timeout=VERSION_TIMEOUT, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    lines = run.stdout.strip().splitlines()
    parsed = parse_version(lines[0], search=True) if run.returncode == 0 and lines else None
    return parsed[0] if parsed else None


def _local(source: str) -> str | None:
    if source == "widget":
        parsed = parse_version(__version__)
        return parsed[0] if parsed else None
    return local_version(source)


def _number(value: Any) -> float | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok else None


def _load(path: Path) -> dict[str, dict[str, Any]]:
    """Estado valido; tipos errados e valores hostis (versao/URL) sao descartados campo a campo."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("sources")
    except (OSError, ValueError, AttributeError, RecursionError):
        return {}
    state: dict[str, dict[str, Any]] = {}
    for source in SOURCES:
        e = raw.get(source) if isinstance(raw, dict) else None
        if isinstance(e, dict):
            latest, local = parse_version(e.get("latest")), parse_version(e.get("local"))
            state[source] = {"checked_at": _number(e.get("checked_at")), "latest": latest and latest[0],
                             "url": _release_url(e.get("url")), "local": local and local[0]}
    return state


def apply_updates(status: dict[str, Any], config: Any, cache_file: Path, now: datetime, online: bool = True) -> None:
    """Preenche `status["updates"]` = {enabled, items: {fonte: {latest, current, available, url?}}}.

    `online=False` so le o estado salvo (reaplicar configuracao nao consulta a rede nem executa nada)."""
    enabled = update_check_enabled(config)
    items: dict[str, Any] = {}
    status["updates"] = {"enabled": enabled, "items": items}
    if not enabled:
        return
    path, now_ts, changed = cache_file.with_name(STATE_FILENAME), now.timestamp(), False
    state = _load(path)
    for source in SOURCES:
        e = state.get(source) or {"checked_at": None, "latest": None, "url": None, "local": None}
        before = dict(e)
        # relogio recuado: checked_at no futuro vale "agora" (espera um dia a partir de agora, sem rajada)
        due = e["checked_at"] is None or now_ts - min(e["checked_at"], now_ts) >= INTERVAL_SECONDS
        if online and due:
            got = _fetch_latest(source)
            e["checked_at"] = now_ts
            if got:
                e["latest"], e["url"] = got
        # o CLI so e executado na consulta diaria ou enquanto ha novidade (para o selo sumir apos atualizar)
        if online and e["latest"] and (due or is_newer(e["latest"], e["local"])):
            e["local"] = _local(source)
        if e != before or source not in state:
            state[source], changed = e, True
        if e["latest"]:
            item = {"latest": e["latest"], "current": e["local"], "available": is_newer(e["latest"], e["local"])}
            if e["url"]:
                item["url"] = e["url"]
            items[source] = item
    if changed:
        try:
            save_secure_json({"version": 1, "sources": state}, path, prefix="updates_")
        except OSError:
            pass  # ponytail: sem gravar, a consulta se repete a cada ciclo; so com disco cheio/sem permissao
