"""Estilos do painel (ticket 32): configuração validada e cada estilo x modo x orientação renderizando de verdade
em qml6 offscreen (opcional), sem corte, com a cor só pelo nível do contrato e as regras do Notch preservadas."""
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_usage_collector.contract import build_agent_account_status
from test_plasmoid_notch_render import COMPACT_FILES, render

UI_DIR = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui"
CONFIG = UI_DIR.parent / "config" / "main.xml"
needs_qml = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")

STYLES = ("pill", "ring", "text", "bar")
MODES = ("ring", "ringpct", "pct")


def iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


def acc(provider, native, weekly, nl="normal", wl="normal", active=True, **extra):
    a = build_agent_account_status(
        provider=provider, account_id=provider[0], label=provider, source="auto", health={"status": "valid"}, is_active=active,
        native_window=None if native is None else {"usage_percentage": native, "release_time": iso(timedelta(hours=2)), "window_seconds": 18000},
        weekly_window=None if weekly is None else {"usage_percentage": weekly, "cycle_reset_time": iso(timedelta(days=3)), "window_seconds": 604800})
    if native is not None:
        a["native_window"]["alert_level"] = nl
    if weekly is not None:
        a["weekly_window"]["alert_level"] = wl
    a.update(extra)
    return a


def agents(*pairs):
    return {p: {"name": p.capitalize(), "accounts": [a]} for p, a in pairs}


# Pior caso de largura: "100%" crítico, aviso, sem dado e selos de convite
THREE = agents(("claude", acc("claude", 100, 30, "critical")), ("codex", acc("codex", 85, 50, "warning")), ("gemini", acc("gemini", None, None, no_data=True)))


def js(tmp_path, expr):
    (tmp_path / "PanelStyle.js").write_text((UI_DIR / "PanelStyle.js").read_text())
    (tmp_path / "t.qml").write_text('import QtQuick\nimport "PanelStyle.js" as PS\nItem { Timer { interval: 50; running: true; onTriggered: { '
                                    'console.log("RESULT " + JSON.stringify(%s)); Qt.quit() } } }' % expr)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", str(tmp_path / "t.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next(l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l)
    return json.loads(line.split("RESULT ", 1)[1])


# ---- estruturais (sem qml6) ----

def test_panel_options_declared_with_defaults_that_keep_todays_look():
    xml = CONFIG.read_text(encoding="utf-8")
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    defaults = {"panelStyle": "pill", "panelMode": "ring", "ringCenter": "logo", "metricSize": "100", "panelMargin": "4"}
    for name, default in defaults.items():
        body = xml.split(f'name="{name}"')[1].split("</entry>")[0]
        assert f"<default>{default}</default>" in body and f"cfg_{name}" in cfg
    assert "<min>80</min>" in xml and "<max>160</max>" in xml and "<max>16</max>" in xml


def test_config_page_validates_and_is_accessible():
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    assert "PanelStyle.config(" in cfg and "panelNow" in cfg  # valor inválido do arquivo cai no padrão
    block = cfg[cfg.index("Estilo do painel (ticket 32)"):] if "Estilo do painel (ticket 32)" in cfg else cfg
    for needle in ("Estilo do painel", "Modo de exibição do painel", "Centro do anel", "Tamanho das métricas", "Margem interna"):
        assert re.search(r'Accessible\.name: configRoot\.safeI18n\("%s' % needle, block)
    assert 'Accessible.description: configRoot.safeI18n("Pílula:' in cfg  # texto de ajuda dos estilos
    assert "from: 80" in cfg and "to: 160" in cfg


def test_styles_keep_contract_level_color_and_non_color_cues():
    item = (UI_DIR / "PanelItem.qml").read_text(encoding="utf-8")
    bars = (UI_DIR / "LevelBars.qml").read_text(encoding="utf-8")
    ring = (UI_DIR / "DualRing.qml").read_text(encoding="utf-8")
    compact = (UI_DIR / "CompactRepresentation.qml").read_text(encoding="utf-8")
    for src in (item, bars, compact, (UI_DIR / "PanelStyle.js").read_text(encoding="utf-8")):
        assert "< 70" not in src and "<= 90" not in src and "usage_percentage" not in src  # nunca limiares fixos
    assert "levelColor" in item and "setLineDash" in bars and "elapsed" in bars.lower()
    assert "setLineDash" in ring and "SessionMark" in ring and "SessionMark" in item
    assert "reducedMotion" in item and "Kirigami.Units.longDuration === 0" in compact
    assert "textFormat: Text.PlainText" in item and "Accessible.name" in compact and "Accessible.description" in compact
    assert 'Keys.onSpacePressed' in compact and 'Keys.onReturnPressed' in compact and "idle" in compact


# ---- configuração (qml6 só para executar o JS) ----

@needs_qml
def test_config_invalid_values_fall_back_to_defaults(tmp_path):
    default = {"style": "pill", "mode": "ring", "center": "logo", "scale": 1.0, "margin": 4}
    bad = [{}, None, {"panelStyle": "zzz", "panelMode": 3, "ringCenter": None, "metricSize": "abc", "panelMargin": None},
           {"metricSize": 9999, "panelMargin": -3}, {"metricSize": 20, "panelMargin": 17}, {"metricSize": None, "panelMargin": "NaN"}]
    out = js(tmp_path, "[%s]" % ",".join("PS.config(%s)" % json.dumps(b) for b in bad) + ".concat([PS.config({metricSize: NaN, panelMargin: Infinity})])")
    assert all(o == default for o in out)
    ok = js(tmp_path, 'PS.config({panelStyle: "bar", panelMode: "pct", ringCenter: "logopct", metricSize: 130, panelMargin: 8})')
    assert ok == {"style": "bar", "mode": "pct", "center": "logopct", "scale": 1.3, "margin": 8}


@needs_qml
def test_headline_picks_most_urgent_window_and_never_invents_zero(tmp_path):
    out = js(tmp_path, """[
      PS.headline({innerPct: 40, innerLevel: "normal", outerPct: 30, outerLevel: "normal"}),
      PS.headline({innerPct: 40, innerLevel: "normal", outerPct: 30, outerLevel: "warning"}),
      PS.headline({innerPct: -1, innerLevel: "", outerPct: 55, outerLevel: "normal"}),
      PS.headline({innerPct: -1, innerLevel: "", outerPct: -1, outerLevel: ""}),
      PS.pctText(-1), PS.pctText(39.6), PS.levelMark("normal"), PS.levelMark("warning"), PS.levelMark("critical"), PS.levelMark("")]""")
    assert out[0] == {"pct": 40, "level": "normal"} and out[1] == {"pct": 30, "level": "warning"}
    assert out[2] == {"pct": 55, "level": "normal"} and out[3]["pct"] == -1
    assert out[4] == "—" and out[5] == "40%"
    assert len(set(out[6:])) == 4  # normal, atenção, crítico e sem nível têm formas diferentes


# ---- renderização ----

@pytest.fixture(scope="module")
def matrix(tmp_path_factory):
    """Estilo x modo x orientação, no tamanho preferido e no mínimo; um subprocesso qml6 por combinação."""
    if shutil.which("qml6") is None:
        pytest.skip("qml6 binary not available")
    root = tmp_path_factory.mktemp("styles")

    def one(args):
        sty, mode, vert = args
        d = root / f"{sty}_{mode}_{vert}"
        for n in "ab":
            (d / n).mkdir(parents=True)
        panel = {"panelStyle": sty, "panelMode": mode}
        big = (460, 40) if not vert else (40, 330)
        r0 = render(d / "a", "", THREE, vertical=vert, invites=3, panel=panel, size=big, extra_cfg={"showSession": True, "sessionOverlay": {"c": "busy", "x": "waiting"}})
        mn = (r0["min"][0], r0["min"][1])  # no mínimo que o painel pode dar
        r1 = render(d / "b", "", THREE, vertical=vert, invites=3, panel=panel, size=mn, extra_cfg={"showSession": True, "sessionOverlay": {"c": "busy", "x": "waiting"}})
        return (sty, mode, vert), {"big": r0, "min": r1}

    jobs = [(s, m, v) for s in STYLES for m in MODES for v in (False, True)]
    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(one, jobs))


@needs_qml
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("vertical", (False, True))
def test_every_style_fits_without_clipping_horizontal_and_vertical(matrix, style, mode, vertical):
    r = matrix[(style, mode, vertical)]
    for key in ("big", "min"):
        out = r[key]
        w, h = out["size"]
        assert len(out["items"]) == 3
        for it in out["items"]:  # nenhum item fora da área do widget
            assert it["x"] >= -0.5 and it["y"] >= -0.5 and it["x"] + it["w"] <= w + 0.5 and it["y"] + it["h"] <= h + 0.5, (key, it, (w, h))
        # o conteúdo real (fontes de verdade) cabe na caixa calculada
        assert out["grid"]["w"] <= out["items"][0]["w"] + 1 and out["grid"]["h"] <= out["items"][0]["h"] + 1, (key, out["grid"], out["items"][0])
    assert r["min"]["min"][0] <= r["big"]["pref"][0] or vertical  # mínimo nunca excede o preferido no eixo do comprimento
    assert r["min"]["min"][1] <= r["big"]["pref"][1] or not vertical


@needs_qml
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("mode", MODES)
def test_modes_show_what_they_promise_and_never_a_false_zero(matrix, style, mode):
    items = matrix[(style, mode, False)]["big"]["items"]
    claude, codex, gemini = items
    if mode == "ring":
        assert all(i["pct"] is None for i in items)           # só o gráfico: sem %
    else:
        assert claude["pct"] == "100%" and codex["pct"] == "85%"
        assert gemini["pct"] == "—"                      # sem dado: "—", nunca 0%
    assert all(i["pct"] != "0%" for i in items)
    # nível também por forma (texto/ícone), não só cor: crítico ■ e atenção ▲; o Text mostra ● no normal
    marks = [i["mark"] for i in items]
    if style == "text" and mode != "pct":
        assert marks == ["■", "▲", "○"]
    elif style in ("bar", "text") or mode == "pct":
        assert marks[:2] == ["■", "▲"] and marks[2] is None
    # acessibilidade: provedor, % e nível em palavras
    assert claude["name"] == "Claude" and "crítico" in claude["desc"] and "100%" in claude["desc"]
    assert "atenção" in codex["desc"] and "sem dados" in gemini["desc"].lower() or "sem nível" in gemini["desc"]


@needs_qml
def test_ring_center_pct_and_logo_options(tmp_path):
    for n in ("a", "b", "c"):
        (tmp_path / n).mkdir()
    one = agents(("claude", acc("claude", 40, 30)))
    for n, center in (("a", "pct"), ("b", "logopct"), ("c", "logo")):
        out = render(tmp_path / n, "", one, panel={"panelStyle": "pill", "ringCenter": center, "metricSize": 160}, size=(200, 60))
        assert out["panel"]["center"] == center
        assert out["geo"]["unit"] >= 28  # com anel grande cabe o % no centro (pequeno cai no logo)


@needs_qml
def test_invalid_config_renders_exactly_like_the_default(tmp_path):
    for n in ("a", "b"):
        (tmp_path / n).mkdir()
    ag = agents(("claude", acc("claude", 40, 30)), ("codex", acc("codex", 85, 50, "warning")))
    base = render(tmp_path / "a", "", ag, extra_cfg=None)
    bad = render(tmp_path / "b", "", ag, panel={"panelStyle": "zzz", "panelMode": "x", "ringCenter": [], "metricSize": 5000, "panelMargin": "NaN"})
    assert bad["panel"] == base["panel"] and bad["geo"] == base["geo"] and bad["pref"] == base["pref"] and bad["min"] == base["min"]


@needs_qml
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("vertical", (False, True))
def test_focus_enter_space_hover_and_idle_sliver_work_in_every_style(tmp_path, style, vertical):
    for n in ("a", "b"):
        (tmp_path / n).mkdir()
    ag = agents(("claude", acc("claude", 40, 30)))
    drive = """
    tc.mouseMove(c, 20, 20); tc.mouseClick(c, 20, 20);
    c.forceActiveFocus(); tc.keyClick(Qt.Key_Return); tc.keyClick(Qt.Key_Space); tc.keyClick(Qt.Key_Enter);
    tc.keyClick(Qt.Key_Escape);
    """
    out = render(tmp_path / "a", "", ag, vertical=vertical, drive=drive, panel={"panelStyle": style, "panelMode": "ringpct"}, size=(300, 200) if not vertical else (80, 300))
    assert out["calls"] == ["hover:true", "click", "close"]
    assert out["expanded"] is True  # Enter, Space, Enter: abre, fecha, abre
    idle = render(tmp_path / "b", "", ag, vertical=vertical, drive="logic.idleHidden = true; c.idle;", panel={"panelStyle": style})
    sliver = 18  # Kirigami.Units.gridUnit do stub
    assert idle["min"][1 if vertical else 0] == sliver  # fatia ociosa do ticket 37 em todos os estilos
