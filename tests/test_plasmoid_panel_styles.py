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
THREE = agents(("claude", acc("claude", 100, 30, "critical", health={"status": "session_expired"})), ("codex", acc("codex", 85, 50, "warning")), ("gemini", acc("gemini", None, None, no_data=True)))


UPDATES = {"enabled": True, "items": {"widget": {"latest": "9.0.0", "available": True, "url": ""},
                                      "claude": {"latest": "2.1.0", "available": True}}}
OVERLAY = {"showSession": True, "sessionOverlay": {"claude/c": "busy", "codex/x": "waiting"}}
DARK = "#15171b"


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def js(tmp_path, expr):
    for f in ("PanelStyle.js", "I18n.js", "ViewPrefs.js", "Presets.js"):
        (tmp_path / f).write_text((UI_DIR / f).read_text())
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
    defaults = {"panelStyle": "pill", "panelMode": "ring", "ringCenter": "logo", "metricSize": "100", "panelMargin": "-1"}  # margem -1 = automática (smallSpacing)
    for name, default in defaults.items():
        body = xml.split(f'name="{name}"')[1].split("</entry>")[0]
        assert f"<default>{default}</default>" in body and f"cfg_{name}" in cfg
    assert "<min>80</min>" in xml and "<max>160</max>" in xml and "<max>16</max>" in xml and "<min>-1</min>" in xml


def test_config_page_validates_and_is_accessible():
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    assert "PanelStyle.config(" in cfg and "panelNow" in cfg  # valor inválido do arquivo cai no padrão
    block = cfg[cfg.index("// Estilo do painel: Pílula"):cfg.index("// Aba Popup")]
    # todo controle do bloco tem Accessible.name e todo rótulo é texto puro
    for ctl in ("QQC2.ComboBox {", "QQC2.SpinBox {", "QQC2.CheckBox {"):
        for chunk in block.split(ctl)[1:]:
            assert "Accessible.name: I18n.tr(" in chunk.split("\n" + " " * 24 + "}\n")[0], (ctl, chunk[:120])
    for chunk in block.split("QQC2.Label {")[1:]:
        assert "textFormat: Text.PlainText" in chunk.split("\n" + " " * 24 + "}\n")[0]
    assert block.count("QQC2.ComboBox {") == 3 and block.count("QQC2.SpinBox {") == 2
    assert 'Accessible.description: I18n.tr("Pill:' in block  # texto de ajuda dos estilos
    assert "40 px of width" in block and "28 px" in block and "Chart only" in block  # limites documentados
    assert "from: 80" in block and "to: 160" in block and "to: 16" in block


def test_styles_keep_contract_level_color_and_non_color_cues():
    item = (UI_DIR / "PanelItem.qml").read_text(encoding="utf-8")
    bars = (UI_DIR / "LevelBars.qml").read_text(encoding="utf-8")
    ring = (UI_DIR / "DualRing.qml").read_text(encoding="utf-8")
    compact = (UI_DIR / "CompactRepresentation.qml").read_text(encoding="utf-8")
    for src in (item, bars, compact, (UI_DIR / "PanelStyle.js").read_text(encoding="utf-8")):
        assert "< 70" not in src and "<= 90" not in src and "usage_percentage" not in src  # nunca limiares fixos
    assert "levelColor" in item and "setLineDash" in bars and "elapsed" in bars.lower()
    assert item.count("Accessible.ignored: true") == 3 and "Loader {" in item  # leitor de tela sem duplicar; só um gráfico
    assert "PanelStyle.barWidth" in bars and "barsWidth" in item  # largura da barra em um lugar só
    assert "setLineDash" in ring and "SessionMark" in ring and "SessionMark" in item
    assert "reducedMotion" in item and "Kirigami.Units.longDuration === 0" in compact
    assert "textFormat: Text.PlainText" in item and "Accessible.name" in compact and "Accessible.description" in compact
    assert 'Keys.onSpacePressed' in compact and 'Keys.onReturnPressed' in compact and "idle" in compact


# ---- configuração (qml6 só para executar o JS) ----

@needs_qml
def test_config_invalid_values_fall_back_to_defaults(tmp_path):
    default = {"style": "pill", "mode": "ring", "center": "logo", "scale": 1.0, "margin": -1}
    bad = [{}, None, {"panelStyle": "zzz", "panelMode": 3, "ringCenter": None, "metricSize": "abc", "panelMargin": None},
           {"metricSize": 9999, "panelMargin": -3}, {"metricSize": 20, "panelMargin": 17}, {"panelMargin": -2}, {"metricSize": None, "panelMargin": "NaN"}]
    out = js(tmp_path, "[%s]" % ",".join("PS.config(%s)" % json.dumps(b) for b in bad) + ".concat([PS.config({metricSize: NaN, panelMargin: Infinity})])")
    assert all(o == default for o in out)
    ok = js(tmp_path, 'PS.config({panelStyle: "bar", panelMode: "pct", ringCenter: "logopct", metricSize: 130, panelMargin: 8})')
    assert ok == {"style": "bar", "mode": "pct", "center": "logopct", "scale": 1.3, "margin": 8}
    # Text não tem "só o gráfico": vale como gráfico e % (só no Text)
    assert js(tmp_path, 'PS.config({panelStyle: "text", panelMode: "ring"}).mode') == "ringpct"
    assert js(tmp_path, 'PS.config({panelStyle: "bar", panelMode: "ring"}).mode') == "ring"


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
        r0 = render(d / "a", "", THREE, vertical=vert, invites=3, panel=panel, size=big, extra_cfg=OVERLAY, updates=UPDATES)
        mn = (r0["min"][0], r0["min"][1])  # no mínimo que o painel pode dar
        r1 = render(d / "b", "", THREE, vertical=vert, invites=3, panel=panel, size=mn, extra_cfg=OVERLAY, updates=UPDATES)
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
        # selos de saúde, ponto de CLI, selo ↑ do widget e convites: todos visíveis, dentro da área, sobre fundo escuro
        assert sorted(b["name"] for b in out["badges"]) == sorted(["Session expired", "New CLI version available",
                                                                   "New widget version available", "3 invites available"]), out["badges"]
        for b in out["badges"]:
            assert b["bg"] == DARK and b["x"] >= -0.5 and b["y"] >= -0.5 and b["x"] + b["w"] <= w + 0.5 and b["y"] + b["h"] <= h + 0.5, (key, b, (w, h))
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
    if mode == "ring" and style != "text":  # no Text, "só o gráfico" vale como gráfico e % (M1)
        assert all(i["pct"] is None for i in items)           # só o gráfico: sem %
    else:
        assert claude["pct"] == "100%" and codex["pct"] == "85%"
        assert gemini["pct"] == "—"                      # sem dado: "—", nunca 0%
    assert all(i["pct"] != "0%" for i in items)
    # nível também por forma (texto/ícone), não só cor: crítico ■ e atenção ▲; o Text mostra ● no normal
    marks = [i["mark"] for i in items]
    if style == "text" and mode != "pct":  # Text: marca sempre visível (ponto/forma) com %
        assert marks == ["■", "▲", "○"]
    elif style in ("bar", "text") or mode == "pct":
        assert marks[:2] == ["■", "▲"] and marks[2] is None
    # acessibilidade: provedor, % e nível em palavras
    assert claude["name"] == "Claude" and "critical" in claude["desc"] and "100%" in claude["desc"]
    assert "warning" in codex["desc"] and "no data" in gemini["desc"].lower() or "no level" in gemini["desc"]


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


# ---- revisão do ticket 32 ----

@needs_qml
def test_text_style_default_mode_shows_percent_and_dot_and_pct_mode_differs(matrix):
    ring = matrix[("text", "ring", False)]["big"]["items"]
    ringpct = matrix[("text", "ringpct", False)]["big"]["items"]
    pct = matrix[("text", "pct", False)]["big"]["items"]
    assert [(i["pct"], i["mark"]) for i in ring] == [(i["pct"], i["mark"]) for i in ringpct]  # M1
    assert [i["pct"] for i in ring] == ["100%", "85%", "\u2014"] and ring[2]["mark"] == "\u25CB"
    assert [i["mark"] for i in pct] == ["\u25A0", "\u25B2", None]  # só %: marca apenas em atenção/crítico


@needs_qml
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("width", (24, 30, 40))
def test_vertical_panel_thickness_degrades_instead_of_clipping(tmp_path, style, width):
    (tmp_path / "a").mkdir()
    out = render(tmp_path / "a", "", THREE, vertical=True, invites=3, updates=UPDATES, panel={"panelStyle": style, "panelMode": "ringpct"}, size=(width, 400))
    assert out["pref"][0] >= out["min"][0]  # preferida nunca abaixo da mínima (M2)
    order = ["bar", "text", "pill"] if style == "bar" else [style, "pill"] if style != "pill" else ["pill"]
    assert out["style"] in order  # só degrada pela cadeia Bar -> Text -> Pílula (Ring -> Pílula)
    if width >= 40:
        assert out["style"] == style  # com a espessura mínima do estilo, nada degrada
    if width == 30 and style == "bar":
        assert out["style"] != "bar"  # Bar vertical não cabe em 30 px: usa Text
    if width >= 30:  # a partir da espessura mínima da Pílula (28 px), nunca há corte
        for it in out["items"]:
            assert it["x"] >= -0.5 and it["x"] + it["w"] <= width + 0.5, (it, width)
        assert out["grid"]["w"] <= out["items"][0]["w"] + 1
        for b in out["badges"]:
            assert b["x"] >= -0.5 and b["x"] + b["w"] <= width + 0.5, b
    assert out["min"][0] <= max(width, out["pref"][0])


@needs_qml
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("vertical", (False, True))
def test_badges_keep_dark_backdrop_on_a_light_theme_and_meet_contrast(tmp_path, style, vertical):
    for n in "ab":
        (tmp_path / n).mkdir()
    for n, bg in (("a", "#f5f5f5"), ("b", "#1b1e20")):  # janela clara e escura
        out = render(tmp_path / n, "", THREE, vertical=vertical, invites=3, updates=UPDATES, bg=bg, extra_cfg=OVERLAY, size=(40, 420) if vertical else None,
                     panel={"panelStyle": style, "panelMode": "ringpct"})
        assert len(out["badges"]) == 4
        for b in out["badges"]:
            assert b["bg"] == DARK, (style, bg, b)  # fundo escuro próprio, também no Ring (M3)
            if b["color"] != "#c24d00":  # formas (pontos/selos): >= 3:1 sobre o fundo
                assert contrast(b["color"], b["bg"]) >= 3, b
        assert all(i["bg"] if "bg" in i else True for i in out["items"])
    # texto do selo de convites (branco sobre #c24d00): >= 4,5:1
    assert contrast("#ffffff", "#c24d00") >= 4.5


@needs_qml
@pytest.mark.parametrize("vertical", (False, True))
def test_percent_center_grows_ring_to_fit_and_falls_back_on_thin_panels(tmp_path, vertical):
    for n in "abc":
        (tmp_path / n).mkdir()
    one = agents(("claude", acc("claude", 40, 30)))
    size = (300, 60) if not vertical else (60, 300)
    for n, center in (("a", "pct"), ("b", "logopct")):
        out = render(tmp_path / n, "", one, vertical=vertical, panel={"panelStyle": "pill", "ringCenter": center}, size=size)
        assert out["geo"]["unit"] >= 28 and out["eff"]["center"] == center  # M4: o anel cresce sozinho (metricSize 100)
    thin = (300, 30) if not vertical else (30, 300)
    out = render(tmp_path / "c", "", one, vertical=vertical, panel={"panelStyle": "pill", "ringCenter": "pct"}, size=thin)
    assert out["eff"]["center"] == "logo"  # painel fino: volta ao logo, sem cortar
    for it in out["items"]:
        assert it["x"] >= -0.5 and it["y"] >= -0.5 and it["x"] + it["w"] <= thin[0] + 0.5 and it["y"] + it["h"] <= thin[1] + 0.5


@needs_qml
def test_auto_margin_uses_small_spacing_until_user_sets_one(tmp_path):
    for n in "ab":
        (tmp_path / n).mkdir()
    one = agents(("claude", acc("claude", 40, 30)))
    auto = render(tmp_path / "a", "", one)
    assert auto["panel"]["margin"] == -1 and auto["pref"][1] == 22 + 2 * 4  # smallSpacing do stub = 4 px
    mine = render(tmp_path / "b", "", one, panel={"panelMargin": 10})
    assert mine["panel"]["margin"] == 10 and mine["pref"][1] == 22 + 2 * 10


@needs_qml
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("vertical", (False, True))
@pytest.mark.parametrize("along", (110, 160, 220))
def test_short_length_degrades_or_shrinks_instead_of_overflowing(tmp_path, style, vertical, along):
    """P2b: com pouca largura (horizontal) ou altura (vertical) disponível, nada vaza da área nem da cápsula."""
    (tmp_path / "a").mkdir()
    size = (40, along) if vertical else (along, 40)
    out = render(tmp_path / "a", f"short_{style}_{'v' if vertical else 'h'}_{along}", THREE, vertical=vertical, invites=3, updates=UPDATES,
                 panel={"panelStyle": style, "panelMode": "ringpct"}, size=size, extra_cfg=OVERLAY)
    w, h = out["size"]
    for it in out["items"] + out["badges"]:
        assert it["x"] >= -0.5 and it["y"] >= -0.5 and it["x2"] <= w + 0.5 and it["y2"] <= h + 0.5, (it, (w, h))  # x2/y2: canto real (com a escala de último recurso)
    order = ["bar", "text", "pill"] if style == "bar" else [style, "pill"] if style != "pill" else ["pill"]
    assert out["style"] in order
    # preferido segue o pedido (não o degradê por comprimento): o painel pode devolver o espaço depois
    big = render(tmp_path / "b", "", THREE, vertical=vertical, invites=3, updates=UPDATES, panel={"panelStyle": style, "panelMode": "ringpct"},
                 size=(40, 600) if vertical else (600, 40), extra_cfg=OVERLAY) if (tmp_path / "b").mkdir() is None else None
    assert big["style"] == style and out["pref"] == big["pref"]


@needs_qml
def test_pill_at_110px_drops_percent_and_badges_before_shrinking(tmp_path):
    """R2 P3-5: sem espaço para a pílula completa, somem o % e os selos em vez de encolher tudo a ~0,4 (ilegível)."""
    (tmp_path / "a").mkdir()
    out = render(tmp_path / "a", "", THREE, invites=3, updates=UPDATES, panel={"panelStyle": "pill", "panelMode": "ringpct"}, size=(110, 40), extra_cfg=OVERLAY)
    assert out["eff"].get("lean") is True and out["eff"]["mode"] == "ring" and out["badges"] == []
    for it in out["items"]:
        assert (it["x2"] - it["x"]) / it["w"] >= 0.9 and it["x"] >= -0.5 and it["x2"] <= 110.5
    (tmp_path / "b").mkdir()
    big = render(tmp_path / "b", "", THREE, invites=3, updates=UPDATES, panel={"panelStyle": "pill", "panelMode": "ringpct"}, size=(600, 40), extra_cfg=OVERLAY)
    assert not big["eff"].get("lean") and len(big["badges"]) == 4  # com espaço, tudo como antes
