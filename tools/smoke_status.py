"""Gera um status.json de fixture (3 provedores; níveis normal/warning/critical e sem dado) para o smoke do plasmoidviewer.

Uso: python tools/smoke_status.py <arquivo-de-saida>. Só dados inventados; nada lê credenciais ou rede.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

from ai_usage_collector.contract import build_agent_account_status


def build():
    now = datetime.now(timezone.utc)
    iso = lambda **kw: (now + timedelta(**kw)).isoformat()
    nat = lambda pct, level, **kw: {"usage_percentage": pct, "window_seconds": 18000, "release_time": iso(**kw), "alert_level": level, "tokens_used": 120000}
    wk = lambda pct, level: {"usage_percentage": pct, "window_seconds": 604800, "cycle_reset_time": iso(days=3, hours=5), "alert_level": level}
    hist = {"today": 12400, "week": 410000, "month": 1900000, "estimated": False,
            "daily_30d": [{"date": f"2026-10-{d:02d}", "tokens": (d * 7919) % 90000} for d in range(1, 31)], "weekly_3m": [], "monthly_12m": []}
    claude = build_agent_account_status("claude", "work", "Trabalho", "auto", {"status": "valid"}, is_active=True,
                                        native_window=nat(82.0, "warning", hours=1, minutes=20), weekly_window=wk(45.0, "normal"),
                                        manual_invite_count=2, manual_invite_url="https://claude.ai/invite/x")
    claude["token_history"] = hist
    claude2 = build_agent_account_status("claude", "p", "Pessoal", "auto", {"status": "session_expired"}, native_window=nat(12.0, "normal", hours=3))
    codex = build_agent_account_status("codex", "cx", "Codex Pro", "auto", {"status": "valid"}, is_active=True,
                                       native_window=nat(95.0, "critical", minutes=25), weekly_window=wk(60.0, "normal"))
    gemini = build_agent_account_status("gemini", "g", "Gemini", "auto", {"status": "valid"}, is_active=True,
                                        native_window=nat(15.0, "normal", hours=2))  # sem janela semanal
    gemini2 = build_agent_account_status("gemini", "g2", "Gemini vazio", "auto", {"status": "valid"})
    gemini2["no_data"] = True
    return {"version": 2, "generated_at": now.isoformat(),
            "agents": {"claude": {"name": "Claude", "accounts": [claude, claude2]}, "codex": {"name": "Codex", "accounts": [codex]},
                       "gemini": {"name": "Gemini", "accounts": [gemini, gemini2]}}}


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(build(), f)
