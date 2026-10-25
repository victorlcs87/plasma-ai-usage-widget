"""Verificacao de atualizacao (ticket 39): widget (GitHub Releases) e CLIs (npm), no maximo 1x/dia por fonte.

Somente leitura e sem credenciais: hosts fixos (api.github.com, registry.npmjs.org) por https, sem
redirect, sem cookies/token, timeout curto e resposta limitada. Nada e baixado, instalado ou executado
(so `<cli> --version`, sem shell). Texto vindo da rede e nao confiavel: so a versao reconstruida pelo
parser e a URL da release (validada) chegam ao status.json. Qualquer falha e silenciosa.

Estado em `update_check.json` ao lado do status.json (0600, escrita atomica), por fonte:
checked_at/latest/url/local. Falha de rede tambem consome o dia (sem rajada); a ultima versao
conhecida e mantida.

Fluxo (como as notificacoes): sob o lock do status.json so se decide o que consultar (`plan_updates`,
que ja "reserva" o dia gravando checked_at); a REDE e os `--version` rodam FORA do lock (`run_plan`,
orcamento total monotonico de NETWORK_BUDGET para todas as fontes, DNS incluso, em thread daemon) e o
resultado e mesclado depois, sob o lock (`merge_results`). O `--version` de um CLI so reexecuta quando o
binario resolvido muda (caminho, mtime, tamanho) ou na consulta diaria. O PATH e o do processo do
coletor: CLIs em ~/.local/bin ou nvm podem nao aparecer no PATH do Plasmoid (ficam "desconhecidos");
a primeira execucao de um `--version` de node pode ser lenta (timeout de VERSION_TIMEOUT).
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import select
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_usage_collector import __version__
from ai_usage_collector.config import save_secure_json
from ai_usage_collector.refresh import NO_REDIRECT_OPENER, status_lock

STATE_FILENAME = "update_check.json"
INTERVAL_SECONDS = 86400
TIMEOUT = 3.0
VERSION_TIMEOUT = 3.0
MAX_BYTES = 256 * 1024
NETWORK_BUDGET = 5.0  # total para todas as fontes
CHUNK = 4096
MAX_VERSION_OUTPUT = 4096

_REPO = "victorlcs87/plasma-ai-usage-widget"
_RELEASE_URL = re.compile(rf"https://github\.com/{re.escape(_REPO)}/releases/(?:[A-Za-z0-9._~/+-]|%[0-9A-Fa-f]{{2}}){{0,200}}", re.ASCII)
_URL_FORBIDDEN = re.compile(r"\.\.|%2e|%2f|%5c", re.I)
# fonte -> (URL fixa, chave da versao na resposta, nome esperado no npm)
SOURCES: dict[str, tuple[str, str, str | None]] = {
    "widget": (f"https://api.github.com/repos/{_REPO}/releases/latest", "tag_name", None),
    "claude": ("https://registry.npmjs.org/@anthropic-ai/claude-code/latest", "version", "@anthropic-ai/claude-code"),
    "codex": ("https://registry.npmjs.org/@openai/codex/latest", "version", "@openai/codex"),
    "gemini": ("https://registry.npmjs.org/@google/gemini-cli/latest", "version", "@google/gemini-cli"),
}
_OPENER = NO_REDIRECT_OPENER  # testes substituem

_SEMVER = re.compile(r"v?(\d{1,9})\.(\d{1,9})\.(\d{1,9})(?:-([0-9A-Za-z][0-9A-Za-z.-]{0,30}))?(?:\+[0-9A-Za-z.-]{1,30})?", re.ASCII)


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


def _get_json(url: str, deadline: float) -> dict[str, Any] | None:
    left = deadline - time.monotonic()
    if left <= 0:
        return None
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "plasma-ai-usage-widget"})
    try:
        with _OPENER.open(req, timeout=min(TIMEOUT, left)) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            read = getattr(resp, "read1", resp.read)  # read1: volta apos um recv, o prazo e checado entre blocos
            body = b""
            while len(body) <= MAX_BYTES:
                if time.monotonic() >= deadline:
                    return None
                chunk = read(CHUNK)
                if not chunk:
                    break
                body += chunk
        if len(body) > MAX_BYTES:
            return None
        data = json.loads(body)
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _fetch_latest(source: str, deadline: float) -> tuple[str, str | None] | None:
    """(versao canonica, URL da release validada ou None) ou None se a resposta e invalida."""
    url, key, package = SOURCES[source]
    data = _get_json(url, deadline)
    parsed = parse_version(data.get(key)) if data else None
    if not data or not parsed or (package and data.get("name") != package):
        return None
    return parsed[0], _release_url(data.get("html_url")) if source == "widget" else None


def _release_url(value: Any) -> str | None:
    ok = isinstance(value, str) and _RELEASE_URL.fullmatch(value) and not _URL_FORBIDDEN.search(value)
    return value if ok else None


def _signature(binary: str) -> list | None:
    """[caminho resolvido, mtime_ns, tamanho] do binario do CLI (so stat, nada e executado); None se ausente."""
    path = shutil.which(binary)
    if not path or not os.path.isabs(path):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [path, st.st_mtime_ns, st.st_size]


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # antes do wait: o pid ainda nao foi reaproveitado
    except OSError:
        pass


def local_version(binary: str) -> str | None:
    """Versao do CLI instalado via `<binario> --version`: lista de args, sem shell, cwd fixo, grupo proprio.

    A saida e lida em no maximo MAX_VERSION_OUTPUT bytes e o prazo e VERSION_TIMEOUT; ao fim (ou no
    estouro) o grupo de processos inteiro e morto, inclusive netos. None se falhar."""
    sig = _signature(binary)
    if not sig:
        return None
    try:
        proc = subprocess.Popen([sig[0], "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, cwd="/", start_new_session=True)
    except (OSError, ValueError):
        return None
    deadline, out, eof, status = time.monotonic() + VERSION_TIMEOUT, b"", False, None
    try:
        fd = proc.stdout.fileno()
        while len(out) < MAX_VERSION_OUTPUT and (left := deadline - time.monotonic()) > 0:
            if not eof and select.select([fd], [], [], min(left, 0.05))[0]:
                chunk = os.read(fd, MAX_VERSION_OUTPUT - len(out))
                out, eof = out + chunk, eof or not chunk
                continue
            # sem EOF obrigatorio (um neto pode segurar o pipe): a saida do processo encerra a leitura (WNOWAIT: pid nao reaproveitado)
            info = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if info is not None:
                status = info.si_code == os.CLD_EXITED and info.si_status == 0
                while len(out) < MAX_VERSION_OUTPUT and select.select([fd], [], [], 0)[0]:
                    chunk = os.read(fd, MAX_VERSION_OUTPUT - len(out))
                    if not chunk:
                        break
                    out += chunk
                break
            if eof:
                time.sleep(0.01)
    except (OSError, ValueError):
        status = None
    finally:
        _kill_group(proc)
        proc.wait()
        proc.stdout.close()
    for line in out.decode("utf-8", "replace").splitlines() if status else []:  # banner antes da versao e comum
        if parsed := parse_version(line, search=True):
            return parsed[0]
    return None


def _number(value: Any) -> float | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok else None


def _signature_field(value: Any) -> list | None:
    ok = (isinstance(value, list) and len(value) == 3 and isinstance(value[0], str) and len(value[0]) < 4096
          and all(isinstance(v, int) and not isinstance(v, bool) for v in value[1:]))
    return list(value) if ok else None


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
                             "url": _release_url(e.get("url")), "local": local and local[0],
                             "bin": _signature_field(e.get("bin"))}
    return state


def _blank() -> dict[str, Any]:
    return {"checked_at": None, "latest": None, "url": None, "local": None, "bin": None}


def _save(path: Path, state: dict[str, dict[str, Any]]) -> None:
    try:
        save_secure_json({"version": 1, "sources": state}, path, prefix="updates_")
    except OSError:
        pass  # ponytail: sem gravar, a consulta se repete a cada ciclo; so com disco cheio/sem permissao


def _items(state: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items: dict[str, Any] = {}
    for source, e in state.items():
        if e["latest"]:
            items[source] = {"latest": e["latest"], "current": e["local"], "available": is_newer(e["latest"], e["local"])}
            if e["url"]:
                items[source]["url"] = e["url"]
    return items


def apply_updates(status: dict[str, Any], config: Any, cache_file: Path) -> None:
    """Preenche `status["updates"]` = {enabled, items: {fonte: {latest, current, available, url?}}} so do estado salvo."""
    enabled = update_check_enabled(config)
    status["updates"] = {"enabled": enabled, "items": _items(_load(cache_file.with_name(STATE_FILENAME))) if enabled else {}}


def plan_updates(status: dict[str, Any], config: Any, cache_file: Path, now: datetime) -> dict[str, bool]:
    """Chamar sob o lock do status.json. Devolve {fonte: consultar_a_rede?} do que `run_plan` deve fazer.

    Fontes vencidas sao reservadas aqui (checked_at = agora, grava na hora): coletores simultaneos nao as
    repetem e a falha de rede tambem consome o dia. Sem rede nem execucao neste passo."""
    apply_updates(status, config, cache_file)
    if not status["updates"]["enabled"]:
        return {}
    path, now_ts = cache_file.with_name(STATE_FILENAME), now.timestamp()
    state, plan, claimed = _load(path), {}, False
    for source in SOURCES:
        e = state.setdefault(source, _blank())
        # relogio recuado: checked_at no futuro vale "agora" (espera um dia a partir de agora, sem rajada)
        due = e["checked_at"] is None or now_ts - min(e["checked_at"], now_ts) >= INTERVAL_SECONDS
        if due:
            e["checked_at"], plan[source], claimed = now_ts, True, True
        elif source != "widget" and e["latest"] and _signature(source) != e["bin"]:
            plan[source] = False  # binario trocado (atualizacao ou instalacao): so releitura da versao local
    parsed = parse_version(__version__)  # versao do proprio widget: constante, sem processo
    if parsed and state["widget"]["local"] != parsed[0]:
        state["widget"]["local"], claimed = parsed[0], True
    if claimed:
        _save(path, state)
        status["updates"]["items"] = _items(state)
    return plan


def reserve_widget(cache_file: Path, now: datetime) -> None:
    """Busca forcada (sob o lock): consome o dia da fonte `widget` agora e grava a versao local; so ela, nunca as do npm."""
    path = cache_file.with_name(STATE_FILENAME)
    state = _load(path)
    e = state.setdefault("widget", _blank())
    e["checked_at"] = now.timestamp()
    if parsed := parse_version(__version__):
        e["local"] = parsed[0]
    for source in SOURCES:
        state.setdefault(source, _blank())
    _save(path, state)


def forced_outcome(got: tuple[str, str | None] | None) -> dict[str, Any]:
    """Resposta de uma linha da Busca de Atualizacao forcada: nova (versao, url?), atual (versao) ou indisponivel.

    (A saida "desligada" e decidida antes, pela configuracao.)"""
    if not got:
        return {"update": "indisponivel"}
    if is_newer(got[0], __version__):
        return {"update": "nova", "version": got[0], **({"url": got[1]} if got[1] else {})}
    return {"update": "atual", "version": __version__}


def run_plan(plan: dict[str, bool], cache_file: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """FORA do lock: (resultados da rede, {CLI: (assinatura, versao local)}). Nunca levanta por falha de rede.

    A rede tem orcamento total NETWORK_BUDGET; o `--version` so roda para CLIs com versao mais recente conhecida."""
    deadline = time.monotonic() + NETWORK_BUDGET
    results: dict[str, dict[str, Any]] = {}

    def work() -> None:
        for source, fetch in plan.items():
            if fetch:
                try:
                    results[source] = {"got": _fetch_latest(source, deadline)}
                except Exception:  # noqa: BLE001 - nada na consulta pode derrubar a thread nem a coleta
                    results[source] = {"got": None}

    worker = threading.Thread(target=work, daemon=True)  # a thread cobre tambem DNS lento; se estourar, e abandonada
    worker.start()
    worker.join(NETWORK_BUDGET)
    got = {s: dict(r) for s, r in list(results.items())}
    known = _load(cache_file.with_name(STATE_FILENAME))
    local = {s: (_signature(s), local_version(s)) for s in plan
             if s != "widget" and (got.get(s, {}).get("got") or known.get(s, {}).get("latest"))}
    return got, local


def merge_results(cache_file: Path, results: dict[str, dict[str, Any]], locals_: dict[str, Any], config: Any) -> dict[str, Any]:
    """Chamar sob o lock do status.json: mescla no estado atual (relido) e devolve o dicionario de itens."""
    path = cache_file.with_name(STATE_FILENAME)
    state = _load(path)
    for source in set(results) | set(locals_):
        e = state.setdefault(source, _blank())
        if results.get(source, {}).get("got"):
            e["latest"], e["url"] = results[source]["got"]
        if source in locals_:
            sig, version = locals_[source]
            if sig is None and e["bin"] and source not in results:
                continue  # binario "sumiu" fora da consulta diaria (PATH diferente?): mantem o conhecido
            e["bin"], e["local"] = sig, version
    _save(path, state)
    return _items(state) if update_check_enabled(config) else {}
