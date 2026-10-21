"""Saida de status para o modulo custom do Waybar (ticket 27): le o cache, nunca coleta."""

from __future__ import annotations

import json
from html import escape
from typing import Any

# Gravidade crescente; "stale" e "unknown" sao classes neutras, nunca um nivel inventado.
_ORDER = ("normal", "warning", "critical")
_WINDOWS = (("native_window", "janela"), ("weekly_window", "semana"))
FALLBACK = {"text": "—", "tooltip": "Sem dados de uso", "class": "unknown", "alt": "unknown"}


def _clean(value: Any) -> str:
    """Texto nao confiavel (rotulos): uma linha so, escapado para o Pango markup do Waybar."""
    return escape(" ".join(str(value).split())[:60], quote=False)


def _pct(win: Any) -> float | None:
    v = win.get("usage_percentage") if isinstance(win, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def build_waybar(status: Any) -> dict[str, Any]:
    """Classe = pior `alert_level` entre as Contas Ativas no Sistema (inativas nao contam).

    Sem nivel em nenhuma conta ativa: "stale" (dados velhos ou erro/429) ou "unknown" (sem dados/conta).
    """
    texts, lines, levels, pcts, degraded = [], [], [], [], False
    for agent in (status.get("agents") or {}).values():
        for acc in agent.get("accounts") or []:
            if acc.get("isActive") is not True:
                continue
            head = f"{_clean(agent.get('name', acc.get('provider', '?')))} — {_clean(acc.get('label', acc.get('id', '?')))}"
            if acc.get("stale") or acc.get("no_data") or acc.get("fetch_error"):
                degraded = True
                texts.append(f"{_clean(agent.get('name', '?'))} —")
                lines.append(f"{head}: dados desatualizados")
                continue
            used = [p for f, _ in _WINDOWS if (p := _pct(acc.get(f))) is not None]
            top = max(used, default=None)
            texts.append(f"{_clean(agent.get('name', '?'))} {top:.0f}%" if top is not None else f"{_clean(agent.get('name', '?'))} —")
            lines.append(head)
            for field, name in _WINDOWS:
                win = acc.get(field)
                p, lvl = _pct(win), (win or {}).get("alert_level") if isinstance(win, dict) else None
                if p is None:
                    continue
                if lvl in _ORDER:
                    levels.append(lvl)
                    pcts.append(p)
                lines.append(f"  {name}: {p:.0f}%" + (f" ({lvl})" if lvl in _ORDER else ""))
    if not texts:
        return dict(FALLBACK, tooltip="Nenhuma conta ativa no sistema")
    cls = max(levels, key=_ORDER.index) if levels else ("stale" if degraded else "unknown")
    out = {"text": " · ".join(texts), "tooltip": "\n".join(lines), "class": cls, "alt": cls}
    if pcts:
        out["percentage"] = round(max(pcts))
    return out


def waybar_line(status: Any) -> str:
    try:
        out = build_waybar(status)
    except Exception:  # cache de formato inesperado nunca quebra o modulo
        out = FALLBACK
    return json.dumps(out, ensure_ascii=False) + "\n"
