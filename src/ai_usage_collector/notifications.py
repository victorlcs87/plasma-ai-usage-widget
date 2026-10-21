"""Notificacoes de limite pelo `notify-send` (org.freedesktop.Notifications), ticket 25.

O coletor decide e envia. Avisos ja dados ficam em `notified.json`, ao lado do status.json (0600,
escrita atomica), por Conta+janela+ciclo de liberacao. Roda dentro do ciclo de coleta, sob o lock
do status.json (refresh.cycle): coletores simultaneos se serializam e o segundo ja ve o cache.
Dado obsoleto, sem dados, 429 ou leitura local nunca notifica (pace.reliable_pct).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_usage_collector.config import SUPPORTED_PROVIDERS, save_secure_json
from ai_usage_collector.refresh import status_lock
from ai_usage_collector.contract import AGENT_NAMES
from ai_usage_collector.pace import CYCLE_TOLERANCE_SECONDS, _num, _ts, reliable_pct, validate_alerts

STATE_FILENAME = "notified.json"
KINDS = ("warning", "critical", "early")
EARLY_SECONDS = {"native": 30 * 60, "weekly": 24 * 3600}
RETENTION_SECONDS = 14 * 86400
MAX_PER_CYCLE = 5  # o excedente fica para o proximo ciclo (nao e marcado como dado)
SEND_TIMEOUT = 2
DEFAULTS: dict[str, Any] = {"warning": 80.0, "critical": 95.0, "early": True, "reset": False, "muted": []}
_WINDOWS = {"native": ("native_window", "release_time", "nativa"),
            "weekly": ("weekly_window", "cycle_reset_time", "semanal")}


def validate_notify(warning: Any, critical: Any, early: Any, reset: Any, muted: Any) -> str | None:
    """Mensagem de erro, ou None se a configuracao vale (limiares como no alerta: 0 < aviso < crítico <= 100)."""
    if error := validate_alerts("threshold", warning, critical):
        return error.replace("alerta", "notificação")
    if not (isinstance(early, bool) and isinstance(reset, bool)):
        return "Opções de aviso antecipado e de reset devem ser verdadeiro/falso."
    if not (isinstance(muted, list) and all(p in SUPPORTED_PROVIDERS for p in muted)):
        return f"Provedores silenciados inválidos. Válidos: {', '.join(SUPPORTED_PROVIDERS)}."
    return None


def notify_settings(config: Any) -> dict[str, Any]:
    """Configuracao de notificacoes; cada campo invalido volta ao padrao sem afetar os demais."""
    raw = config.get("notifications") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = {**DEFAULTS, "muted": []}
    if validate_alerts("threshold", raw.get("warning"), raw.get("critical")) is None:
        out["warning"], out["critical"] = raw["warning"], raw["critical"]
    for k in ("early", "reset"):
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    if isinstance(raw.get("muted"), list):  # silenciar nunca se perde por outro campo invalido
        out["muted"] = sorted({p for p in raw["muted"] if isinstance(p, str) and p in SUPPORTED_PROVIDERS})
    return out


def _clean(text: Any, limit: int = 60) -> str:
    """Texto nao confiavel (rotulo de Conta): sem controles, uma linha, curto e sem marcacao do servidor."""
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in str(text))
    text = re.sub(r"\s+", " ", text).strip()[:limit]
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def dbus_notify(summary: str, body: str, critical: bool = False) -> bool:
    """Envia uma notificacao pelo D-Bus (notify-send); False se o servico nao existir ou falhar.

    Lista de argumentos, sem shell; `--` impede que o texto seja lido como opcao.
    """
    if not (os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.path.exists(
            os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"), "bus"))):
        return False  # sem barramento de sessao: evita o autolaunch de um dbus-daemon
    cmd = ["notify-send", "--app-name=Plasma AI Usage", f"--urgency={'critical' if critical else 'normal'}",
           "--icon=dialog-warning", "--", summary, body]
    try:
        done = subprocess.run(cmd, shell=False, stdin=subprocess.DEVNULL, capture_output=True, timeout=SEND_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _load(path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("windows")
    except (OSError, ValueError, AttributeError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, e in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(e, dict) and isinstance(e.get("sent"), list) \
                and (release := _num(e.get("release"))) is not None and (seen := _num(e.get("seen"))) is not None:
            out[key] = {"release": release, "seen": seen, "sent": [k for k in e["sent"] if k in KINDS]}
    return out


def _span(seconds: float) -> str:
    return f"{round(seconds / 3600)} h" if seconds >= 5400 else f"{max(1, round(seconds / 60))} min"


def apply_notifications(status: dict[str, Any], config: Any, cache_file: Path, now: datetime, collected: set[str],
                        outbox: list[dict[str, Any]]) -> None:
    """Expoe as configuracoes em `status["notifications"]` e decide os avisos devidos das Contas coletadas.

    Roda sob o lock do status.json: so calcula e grava `notified.json` (avisos marcados como dados);
    o envio fica em `outbox` para `deliver`, fora do lock, que desfaz a marca dos nao entregues.
    """
    cfg = notify_settings(config)
    status["notifications"] = cfg
    path, now_s = cache_file.with_name(STATE_FILENAME), now.timestamp()
    state = _load(path)
    before = json.dumps(state, sort_keys=True)
    queued: list[dict[str, Any]] = []

    def send(summary: str, body: str, critical: bool, muted: bool, key: str, release: float, kinds: list[str]) -> bool:
        if muted:  # silenciado: o aviso e consumido sem enviar (nao ha rajada ao reativar)
            return True
        if len(queued) >= MAX_PER_CYCLE:
            return False
        queued.append({"summary": summary, "body": body, "critical": critical, "key": key, "release": release, "kinds": kinds})
        return True

    live = set()
    for provider in sorted(collected):
        muted, name = provider in cfg["muted"], AGENT_NAMES.get(provider, provider)
        for acc in status["agents"][provider]["accounts"]:
            live.add(f"{provider}:{acc['id']}")
            who = f"Conta {_clean(acc.get('label') or acc['id'])}"
            for kind, (field, release_key, label) in _WINDOWS.items():
                win = acc.get(field)
                pct = reliable_pct(acc, win, release_key) if isinstance(win, dict) else None
                if pct is None:
                    continue
                key, release = f"{provider}:{acc['id']}:{kind}", _ts(win[release_key])
                entry = state.get(key)
                if entry and abs(entry["release"] - release) > CYCLE_TOLERANCE_SECONDS:
                    # Ciclo novo: o limite sinalizado foi liberado (aviso best-effort, sem repeticao)
                    if entry["sent"] and cfg["reset"] and pct < cfg["warning"]:
                        send(f"{name}: janela {label} liberada", f"{who}. Você já pode voltar a usar.", False, muted, key, release, [])
                    entry = None
                entry = state[key] = {**(entry or {"sent": []}), "release": release, "seen": now_s}
                sent = entry["sent"]
                reached = ["warning", "critical"][:(pct >= cfg["warning"]) + (pct >= cfg["critical"])]
                if (todo := [k for k in reached if k not in sent]) and send(
                        f"{name}: janela {label} em {pct:.0f}%",
                        f"{who}. Libera em {_span(release - now_s)}." if release > now_s else f"{who}.",
                        todo[-1] == "critical", muted, key, release, todo):
                    sent += todo
                fc = win.get("forecast")
                secs = _num(fc.get("seconds_until")) if isinstance(fc, dict) else None
                if (cfg["early"] and "early" not in sent and pct < 100 and secs is not None
                        and fc.get("before_release") is True and 0 < secs <= EARLY_SECONDS[kind]
                        and send(f"{name}: janela {label} deve esgotar em ~{_span(secs)}",
                                 f"{who}. No ritmo atual o limite acaba antes da liberação.", False, muted, key, release, ["early"])):
                    sent.append("early")

    # Poda: Contas removidas e ciclos antigos (relogio recuado: `seen` futuro e limitado a agora)
    state = {k: e for k, e in state.items()
             if now_s - min(e["seen"], now_s) <= RETENTION_SECONDS
             and (k.split(":", 1)[0] not in collected or k.rsplit(":", 1)[0] in live)}
    if json.dumps(state, sort_keys=True) != before:
        try:
            save_secure_json({"version": 1, "windows": state}, path, prefix="notified_")
        except OSError as e:
            sys.stderr.write(f"Aviso: avisos ja dados nao gravados ({e}); notificacoes deste ciclo descartadas\n")
            return
    outbox.extend(queued)


def deliver(outbox: list[dict[str, Any]], cache_file: Path) -> None:
    """Envia os avisos fora do lock; o primeiro que falhar encerra o envio (custo maximo: um timeout).

    Os nao entregues perdem a marca em `notified.json` e sao tentados no proximo ciclo.
    """
    failed, down = [], False
    for ev in outbox:
        ok = False
        if not down:
            try:
                ok = dbus_notify(ev["summary"], ev["body"], ev["critical"])
            except Exception:  # o transporte nunca derruba a coleta
                ok = False
            down = not ok
        if not ok:
            failed.append(ev)
    flag = cache_file.with_name("notify_failed")  # falha registrada uma vez so; some quando um envio volta a dar certo
    if not failed:
        if outbox:
            flag.unlink(missing_ok=True)
        return
    if not flag.exists():
        sys.stderr.write("Aviso: notificação do sistema não enviada (notify-send ou serviço de notificações indisponível?)\n")
        try:
            flag.touch()
        except OSError:
            pass
    path = cache_file.with_name(STATE_FILENAME)
    try:
        with status_lock(cache_file.with_name("refresh_state.json")):
            state = _load(path)
            for ev in failed:
                e = state.get(ev["key"])
                if e and abs(e["release"] - ev["release"]) <= CYCLE_TOLERANCE_SECONDS:
                    e["sent"] = [k for k in e["sent"] if k not in ev["kinds"]]
            save_secure_json({"version": 1, "windows": state}, path, prefix="notified_")
    except OSError as e:
        sys.stderr.write(f"Aviso: avisos nao entregues nao desmarcados ({e})\n")
