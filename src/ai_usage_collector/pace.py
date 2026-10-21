"""Ritmo de Uso, Previsao de Esgotamento e nivel de alerta por janela (ticket 24).

Amostras (usage_percentage lido da API) ficam em `samples.json`, ao lado do status.json (0600,
escrita atomica). Sem dado confiavel (obsoleto, sem dados, 429, leitura local, poucas amostras)
nao ha previsao: nenhum valor e inventado.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json

from ai_usage_collector.config import save_secure_json

SAMPLES_FILENAME = "samples.json"
LOOKBACK_SECONDS = {"native": 30 * 60, "weekly": 24 * 3600}
_WINDOWS = {"native": ("native_window", "release_time"), "weekly": ("weekly_window", "cycle_reset_time")}
MIN_SPAN_SECONDS = 60  # abaixo disso a inclinacao e ruido
MIN_ELAPSED_FRACTION = 0.02  # logo apos o reset o ritmo oscila demais para valer
CYCLE_TOLERANCE_SECONDS = 300  # o provedor oscila o horario de liberacao em alguns segundos
MAX_SAMPLES = 2000
DEFAULT_ALERTS = {"mode": "pace", "warning": 70.0, "critical": 90.0}
LEVEL_KEYS = ("pace", "forecast", "alert_level")


def validate_alerts(mode: Any, warning: Any, critical: Any) -> str | None:
    """Mensagem de erro, ou None se o modo e os limiares (0 < warning < critical <= 100) valem."""
    if mode not in ("pace", "threshold"):
        return "Modo de alerta inválido. Use 'pace' (ritmo) ou 'threshold' (limiar fixo)."
    nums = [warning, critical]
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in nums):
        return "Limiares de alerta devem ser números."
    if not 0 < warning < critical <= 100:
        return "Limiares inválidos: exija 0 < aviso < crítico <= 100."
    return None


def alert_settings(config: Any) -> dict[str, Any]:
    """Configuracao de alerta; qualquer valor invalido volta ao padrao (ritmo, 70/90)."""
    raw = config.get("alerts") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    merged = {**DEFAULT_ALERTS, **{k: raw[k] for k in DEFAULT_ALERTS if k in raw}}
    return merged if validate_alerts(**merged) is None else dict(DEFAULT_ALERTS)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _ts(value: Any) -> float | None:
    try:
        when = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp()


def _load(path: Path) -> dict[str, Any]:
    try:
        series = json.loads(path.read_text(encoding="utf-8")).get("series")
    except (OSError, ValueError, AttributeError):
        return {}
    return {k: v for k, v in series.items() if isinstance(v, dict)} if isinstance(series, dict) else {}


def _update_samples(entry: dict[str, Any], pct: float, release: float, window_s: float | None,
                    lookback: int, now: float) -> list[tuple[float, float]]:
    """Amostras validas do ciclo atual, mais a leitura de agora; `entry` guarda o resultado."""
    old_release = _num(entry.get("release"))
    same_cycle = old_release is not None and abs(old_release - release) <= CYCLE_TOLERANCE_SECONDS
    start = max(now - lookback, release - window_s - CYCLE_TOLERANCE_SECONDS) if window_s else now - lookback
    kept: list[tuple[float, float]] = []
    for raw in (entry.get("samples") if same_cycle and isinstance(entry.get("samples"), list) else []):
        t, p = (_num(raw[0]), _num(raw[1])) if isinstance(raw, (list, tuple)) and len(raw) == 2 else (None, None)
        if t is not None and p is not None and start <= t <= now and 0 <= p <= 100:
            kept.append((t, p))
    kept = sorted(s for s in kept if s[0] != now) + [(now, pct)]
    for i in range(len(kept) - 1, 0, -1):  # consumo decrescente = reset: ignora o que veio antes
        if kept[i][1] < kept[i - 1][1] - 0.05:
            kept = kept[i:]
            break
    kept = kept[-MAX_SAMPLES:]
    entry["release"], entry["samples"] = release, [list(s) for s in kept]
    return kept


def _forecast(samples: list[tuple[float, float]], now: float, release: float) -> dict[str, Any] | None:
    span = samples[-1][0] - samples[0][0]
    if len(samples) < 2 or span < MIN_SPAN_SECONDS:
        return None
    pct, rise = samples[-1][1], samples[-1][1] - samples[0][1]
    if pct >= 100:
        seconds = 0.0
    elif rise <= 0:
        return {"exhausts_at": None, "seconds_until": None, "before_release": False, "basis_seconds": int(span)}
    else:
        seconds = (100 - pct) / (rise / span)
    if seconds > 10 * 365 * 86400:  # inclinacao minima: nao ha esgotamento pratico
        return {"exhausts_at": None, "seconds_until": None, "before_release": False, "basis_seconds": int(span)}
    at = now + seconds
    return {
        "exhausts_at": datetime.fromtimestamp(at, tz=timezone.utc).isoformat(),
        "seconds_until": int(seconds),
        "before_release": at < release,
        "basis_seconds": int(span),
    }


def _level(pct: float, pace: float | None, settings: dict[str, Any]) -> str | None:
    if settings["mode"] == "threshold":
        return "critical" if pct >= settings["critical"] else "warning" if pct >= settings["warning"] else "normal"
    if pct >= 100:
        return "critical"
    if pace is None:
        return None
    if pace > 1:
        return "critical" if pct >= 90 else "warning"
    return "normal"


def apply_pace(status: dict[str, Any], config: Any, cache_file: Path, now: datetime, collected: set[str]) -> None:
    """Anexa `pace`, `forecast` e `alert_level` a cada janela das Contas coletadas neste ciclo."""
    path = cache_file.with_name(SAMPLES_FILENAME)
    old, settings, now_s = _load(path), alert_settings(config), now.timestamp()
    status["alerts"] = settings  # a tela de configuracao le o modo e os limiares aqui
    series = {k: v for k, v in old.items() if k.split(":", 1)[0] not in collected}
    for provider in collected:
        for acc in status["agents"][provider]["accounts"]:
            fresh = not acc.get("stale") and not acc.get("no_data")
            for name, (field, release_key) in _WINDOWS.items():
                win = acc.get(field)
                if not isinstance(win, dict):
                    continue
                for key in LEVEL_KEYS:  # copiados de leitura anterior (obsoleta): nunca valem
                    win.pop(key, None)
                key = f"{provider}:{acc['id']}:{name}"
                pct = _num(win.get("usage_percentage"))
                if not fresh or pct is None:
                    if key in old:
                        series[key] = old[key]
                    continue
                release = _ts(win.get(release_key))
                reliable = win.get("source") == "api" and release is not None  # local nunca prevê
                pace = None
                elapsed = _num(win.get("elapsed_fraction"))
                if reliable and elapsed is not None and elapsed >= MIN_ELAPSED_FRACTION:
                    pace = round(pct / 100 / elapsed, 2)
                    win["pace"] = pace
                if reliable:
                    entry = old.get(key, {})
                    samples = _update_samples(entry, pct, release, _num(win.get("window_seconds")),
                                              LOOKBACK_SECONDS[name], now_s)
                    series[key] = entry
                    if fc := _forecast(samples, now_s, release):
                        win["forecast"] = fc
                win["alert_level"] = _level(pct, pace, settings)
    save_secure_json({"version": 1, "series": series}, path, prefix="samples_")
