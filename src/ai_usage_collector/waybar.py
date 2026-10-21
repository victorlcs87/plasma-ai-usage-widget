"""Saida de status para o modulo custom do Waybar (ticket 27): le o cache, nunca coleta."""

from __future__ import annotations

import json
import math
import unicodedata
from html import escape
from typing import Any

from ai_usage_collector.collector import load_status_cache

# Gravidade crescente; "stale" e "unknown" sao classes neutras, nunca um nivel inventado.
_ORDER = ("normal", "warning", "critical")
_WINDOWS = (("native_window", "janela"), ("weekly_window", "semana"))
MAX_LINES = 20
FALLBACK = {"text": "—", "tooltip": "Sem dados de uso", "class": "unknown", "alt": "unknown"}


def _clean(value: Any) -> str:
    """Texto nao confiavel (rotulos): uma linha so, escapado para o Pango markup do Waybar."""
    text = "".join(c for c in " ".join(str(value).split()) if not unicodedata.category(c).startswith("C"))
    return escape(text[:60], quote=False)  # sem controles/bidi/surrogates: invalidos no Pango e permitem spoofing


def _pct(win: Any) -> float | None:
    v = win.get("usage_percentage") if isinstance(win, dict) else None
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    return min(max(float(v), 0.0), 100.0) if ok else None  # NaN/Infinity descartados; fora de 0..100 limitado


def build_waybar(status: Any) -> dict[str, Any]:
    """Classe = pior `alert_level` entre as Contas Ativas no Sistema (inativas nao contam).

    Sem nivel em nenhuma conta ativa: "stale" (dados velhos ou erro/429) ou "unknown" (sem dados/conta).
    """
    texts, lines, levels, pcts, degraded = [], [], [], [], False
    for key, agent in (status.get("agents") or {}).items():
        name = _clean(agent["name"] if isinstance(agent.get("name"), str) else key)
        for acc in agent.get("accounts") or []:
            if acc.get("isActive") is not True:
                continue
            head = f"{name} — {_clean(acc.get('label', acc.get('id', '?')))}"
            if acc.get("stale") or acc.get("no_data") or acc.get("fetch_error"):
                degraded = True
                texts.append(f"{name} —")
                lines.append(f"{head}: dados desatualizados")
                continue
            used = [p for f, _ in _WINDOWS if (p := _pct(acc.get(f))) is not None]
            top = max(used, default=None)
            texts.append(f"{name} {top:.0f}%" if top is not None else f"{name} —")
            lines.append(head)
            for field, wname in _WINDOWS:
                win = acc.get(field)
                p, lvl = _pct(win), (win or {}).get("alert_level") if isinstance(win, dict) else None
                if p is None:
                    continue
                if lvl in _ORDER:
                    levels.append(lvl)
                    pcts.append(p)
                lines.append(f"  {wname}: {p:.0f}%" + (f" ({lvl})" if lvl in _ORDER else ""))
    if not texts:
        return dict(FALLBACK, tooltip="Nenhuma conta ativa no sistema")
    cls = max(levels, key=_ORDER.index) if levels else ("stale" if degraded else "unknown")
    out = {"text": " · ".join(texts), "tooltip": "\n".join(lines[:MAX_LINES] + (["…"] if len(lines) > MAX_LINES else [])), "class": cls, "alt": cls}
    if pcts:
        out["percentage"] = round(max(pcts))
    return out


def waybar_line(cache_path: str) -> str:
    """Sempre uma linha JSON ASCII valida (qualquer falha cai no FALLBACK)."""
    try:
        out = build_waybar(load_status_cache(cache_path))
    except Exception:  # cache ausente/invalido/inesperado, cache-path invalido: nunca quebra o modulo
        out = FALLBACK
    return json.dumps(out) + "\n"
