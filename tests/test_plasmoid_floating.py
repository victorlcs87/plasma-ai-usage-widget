"""Notch flutuante (ticket 41): geometria pura por borda/tela e janelas rodando em qml6 offscreen com stubs do Plasma.

NÃO verificável aqui (precisa de Plasma real): layer-shell de verdade (margens aplicadas pelo compositor), vários
monitores, painéis aparecendo/sumindo, arraste com o ponteiro real e o foco/Escape no popup. O que é coberto: a
matemática de posição (FloatingGeometry.js), a aplicação das propriedades anexadas do layer-shell (lidas de volta),
o fallback sem o módulo, a configuração (validação, uma posição por borda) e a renderização das janelas.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_plasmoid_notch_render import STUBS as NOTCH_STUBS
from test_plasmoid_popup import FILES as POPUP_FILES, STUBS as POPUP_STUBS, fixture

UI_DIR = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui"
CONFIG = UI_DIR.parent / "config" / "main.xml"
needs_qml = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")
EDGES = ("top", "bottom", "left", "right")

PLASMOID_STUB = ("module org.kde.plasma.plasmoid\nsingleton Plasmoid 1.0 Plasmoid.qml\n", {
    "Plasmoid.qml": "pragma Singleton\nimport QtQuick\nQtObject { property int formFactor: 2; property var triggered: []\n"
                    " function internalAction(n) { return { trigger: function () { triggered.push(n) } } }\n"
                    " property var configuration: ({}) }"})
CORE_STUB = NOTCH_STUBS["org/kde/plasma/core"]
FILES = tuple(dict.fromkeys(POPUP_FILES + ("CompactRepresentation.qml", "PanelItem.qml", "LevelBars.qml", "FloatingGeometry.js", "FloatingFrame.qml",
                                           "FloatingLayer.qml", "FloatingNotch.qml", "FloatingPillWindow.qml", "FloatingPopupWindow.qml")))


def js(tmp_path, expr):
    for f in ("FloatingGeometry.js",):
        (tmp_path / f).write_text((UI_DIR / f).read_text())
    (tmp_path / "t.qml").write_text('import QtQuick\nimport "FloatingGeometry.js" as FG\nItem { Timer { interval: 50; running: true; onTriggered: { '
                                    'console.log("RESULT " + JSON.stringify(%s)); Qt.quit() } } }' % expr)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", str(tmp_path / "t.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next(l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l)
    return json.loads(line.split("RESULT ", 1)[1])


# ---- estruturais (sem qml6) ----

def test_options_declared_with_safe_defaults():
    xml = CONFIG.read_text(encoding="utf-8")
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    defaults = {"floatingNotch": "false", "floatEdge": "top", "floatSize": "100", "floatSnap": "true", "floatScreen": "",
                "floatOffsetTop": "0", "floatOffsetBottom": "0", "floatOffsetLeft": "0", "floatOffsetRight": "0"}
    for name, default in defaults.items():
        body = xml.split(f'name="{name}"')[1].split("</entry>")[0]
        assert f"<default>{default}</default>" in body and f"cfg_{name}" in cfg, name


def test_layer_shell_import_is_isolated_and_plasmoid_mode_does_not_load_the_floating_code():
    importers = [p.name for p in UI_DIR.glob("*.qml") if "org.kde.layershell" in p.read_text(encoding="utf-8")]
    assert importers == ["FloatingLayer.qml"]  # módulo opcional: só um arquivo, carregado por Loader com fallback
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    assert "active: Plasmoid.configuration.floatingNotch === true" in main and 'source: "FloatingNotch.qml"' in main
    layer = (UI_DIR / "FloatingLayer.qml").read_text(encoding="utf-8")
    assert "exclusionZone = -1" in layer and "AnchorTop | LS.Window.AnchorLeft" in layer  # ignora zonas de painéis
    frame = (UI_DIR / "FloatingFrame.qml").read_text(encoding="utf-8")
    assert "Qt.WindowStaysOnTopHint" in frame and "Qt.Tool" in frame and "I18n.tr(" in frame


def test_config_section_is_accessible_plain_text_and_off_by_default():
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    block = cfg[cfg.index('objectName: "floatingSection"'):cfg.index("// Estilo do painel: Pílula")]
    for ctl in ("QQC2.ComboBox {", "QQC2.SpinBox {", "QQC2.CheckBox {", "QQC2.Button {"):
        for chunk in block.split(ctl)[1:]:
            assert "Accessible.name: I18n.tr(" in chunk.split("\n" + " " * 32 + "}\n")[0], (ctl, chunk[:80])
    for chunk in block.split("QQC2.Label {")[1:]:
        assert "textFormat: Text.PlainText" in chunk.split("\n" + " " * 28 + "}\n")[0]
    assert "layer-shell" in block and "X11" in block and "Wayland" in block  # limitações documentadas na própria tela
    assert "property bool cfg_floatingNotch: false" in cfg


def test_floating_code_keeps_contract_rules():
    for name in ("FloatingNotch.qml", "FloatingPillWindow.qml", "FloatingPopupWindow.qml", "FloatingFrame.qml", "FloatingLayer.qml", "FloatingGeometry.js"):
        src = (UI_DIR / name).read_text(encoding="utf-8")
        assert "usage_percentage" not in src and "< 70" not in src and "alert_level" not in src  # nada de regra de negócio nem cor
    pill = (UI_DIR / "FloatingPillWindow.qml").read_text(encoding="utf-8")
    assert "CompactRepresentation {" in pill and "hosted: true" in pill  # reutiliza o mesmo componente do painel
    assert "FullRepresentation {" in (UI_DIR / "FloatingPopupWindow.qml").read_text(encoding="utf-8")


# ---- geometria (qml6 só para executar o JS) ----

@needs_qml
def test_config_invalid_values_fall_back_to_defaults(tmp_path):
    default = {"enabled": False, "edge": "top", "vertical": False, "scale": 1.0, "offsets": {"top": 0, "bottom": 0, "left": 0, "right": 0}, "snap": True, "screen": ""}
    bad = [{}, None, {"floatEdge": "diagonal", "floatSize": "abc", "floatOffsetTop": "x", "floatScreen": 3, "floatingNotch": "true"},
           {"floatEdge": 7, "floatSize": 9999, "floatOffsetLeft": 99999999, "floatOffsetRight": None},
           {"floatSize": 20, "floatOffsetBottom": -30000}]
    out = js(tmp_path, "[%s]" % ",".join("FG.config(%s)" % json.dumps(b) for b in bad)
             + ".concat([FG.config({floatSize: NaN, floatOffsetTop: NaN, floatOffsetLeft: Infinity})])")
    assert all(o == default for o in out)
    ok = js(tmp_path, 'FG.config({floatingNotch: true, floatEdge: "left", floatSize: 130, floatOffsetLeft: -250, floatOffsetTop: 40, floatSnap: false, floatScreen: " DP-2 "})')
    assert ok == {"enabled": True, "edge": "left", "vertical": True, "scale": 1.3, "offsets": {"top": 40, "bottom": 0, "left": -250, "right": 0},
                  "snap": False, "screen": "DP-2"}


@needs_qml
def test_pill_rect_per_edge_is_flush_clamped_and_inside(tmp_path):
    scr = {"w": 1920, "h": 1080}
    horiz, vert = {"w": 160, "h": 32}, {"w": 32, "h": 160}
    cases = [(e, off, vert if e in ("left", "right") else horiz) for e in EDGES for off in (0, -300, 300, -99999, 99999, None)]
    out = js(tmp_path, json.dumps(cases) + ".map(function (c) { return FG.pillRect(c[0], c[1], c[2], %s) })" % json.dumps(scr))
    for (edge, off, size), r in zip(cases, out):
        assert 0 <= r["x"] and r["x"] + r["w"] <= scr["w"] and 0 <= r["y"] and r["y"] + r["h"] <= scr["h"], (edge, off, r)
        if edge == "top": assert r["y"] == 4
        if edge == "bottom": assert r["y"] + r["h"] == scr["h"] - 4
        if edge == "left": assert r["x"] == 4
        if edge == "right": assert r["x"] + r["w"] == scr["w"] - 4
        if off in (0, None):
            c = (r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
            assert abs((c[1] if edge in ("left", "right") else c[0]) - (scr["h"] if edge in ("left", "right") else scr["w"]) / 2) <= 1
    # deslocamento persistido de uma tela maior: a tela menor reposiciona dentro dela (nunca fora)
    small = js(tmp_path, 'FG.pillRect("top", 5000, {w: 160, h: 32}, {w: 800, h: 600})')
    assert small["x"] + small["w"] == 800 and small["offset"] == 320
    # tela menor que o Notch: encosta no início, sem posição negativa
    tiny = js(tmp_path, 'FG.pillRect("top", 100, {w: 160, h: 32}, {w: 120, h: 90})')
    assert tiny["x"] == 0 and tiny["offset"] == 0


@needs_qml
def test_popup_opens_inward_and_stays_on_screen(tmp_path):
    want = {"w": 450, "h": 504}
    cases = []
    for scr in ({"w": 1920, "h": 1080}, {"w": 800, "h": 600}, {"w": 480, "h": 360}):
        for e in EDGES:
            size = {"w": 32, "h": 160} if e in ("left", "right") else {"w": 160, "h": 32}
            for off in (0, -99999, 99999):
                cases.append((e, off, size, scr))
    out = js(tmp_path, json.dumps(cases) + ".map(function (c) { var p = FG.pillRect(c[0], c[1], c[2], c[3]); return {p: p, q: FG.popupRect(c[0], p, %s, c[3])} })" % json.dumps(want))
    for (edge, off, size, scr), r in zip(cases, out):
        p, q = r["p"], r["q"]
        assert q["x"] >= 0 and q["y"] >= 0 and q["x"] + q["w"] <= scr["w"] and q["y"] + q["h"] <= scr["h"], (edge, scr, q)
        assert q["w"] >= 1 and q["h"] >= 1
        if edge == "top": assert q["y"] >= p["y"] + p["h"]
        if edge == "bottom": assert q["y"] + q["h"] <= p["y"]
        if edge == "left": assert q["x"] >= p["x"] + p["w"]
        if edge == "right": assert q["x"] + q["w"] <= p["x"]


@needs_qml
def test_snap_and_screen_pick(tmp_path):
    out = js(tmp_path, '[FG.snapOffset(8, true), FG.snapOffset(-13, true), FG.snapOffset(5, false), '
                       'FG.pickScreen([{name: "A"}, {name: "B"}], "B", 0), FG.pickScreen([{name: "A"}, {name: "B"}], "Z", 1), '
                       'FG.pickScreen([{name: "A"}], "Z", 5), FG.pickScreen([], "", -1)]')
    assert out == [0, -13, 5, 1, 1, 0, 0]


# ---- janelas (qml6 offscreen, stubs) ----

HARNESS = """
import QtQuick
import QtQuick.Window
import QtTest
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.layershell as LS
import "NotchModel.js" as NotchModel
import "I18n.js" as I18n
Window { id: win; visible: true; width: 20; height: 20
  Item { id: logic
    property var statusData: %(data)s
    property var compactModel: NotchModel.buildModel(statusData, {providerOrder: "claude,codex,gemini", hiddenProviders: ""}, I18n.tr)
    property string worstHealthStatus: NotchModel.worstHealth(compactModel)
    property var updateInfo: NotchModel.updateSummary(statusData, I18n.tr)
    property int totalInvites: 2
    property color accentColor: "#3daee9"
    property string toolTipMainText: "AI"
    property string toolTipSubText: ""
    property bool floatingActive: fn.available
    property bool open: false
    property bool expanded: false
    property bool pinned: false
    property bool pillHovered: false
    property bool idleHidden: false
    property bool inPanel: true
    property bool isRefreshing: false
    property bool isLoading: false
    property string lastError: ""
    property string lastUpdatedFormatted: ""
    property var sessionOverlay: ({})
    property var calls: []
    function setPillHovered(h) { calls.push("hover:" + h) }
    function pillClicked() { calls.push("click"); open = !open }
    function setPopupHovered(h) { calls.push("popupHover:" + h) }
    function closePopup() { calls.push("close"); open = false }
    function refreshCollector() {}
    function loadStatus() {}
  }
  FloatingNotch { id: fn; plasmoidItem: logic; forceLayer: %(layer)s }
  TestCase { id: tc; when: false; name: "t" }
  property var result: ({})
  function rect(w) { return {x: w.x, y: w.y, w: w.width, h: w.height, visible: w.visible} }
  function layerOf(w) { var a = w.LS.Window; return {anchors: a.anchors, ez: a.exclusionZone, ml: a.margins.left, mt: a.margins.top, layer: a.layer, kb: a.keyboardInteractivity, scope: a.scope} }
  Component.onCompleted: Kirigami.Units.longDuration = 200
  function grab(item, path) { if (!path) return; var done = false; item.grabToImage(function (r) { r.saveToFile(path); done = true }); tc.wait(150) }
  Timer { interval: 400; running: true; onTriggered: {
    var scenarios = %(scenarios)s
    for (var i = 0; i < scenarios.length; i++) {
      var s = scenarios[i]
      Plasmoid.configuration = s.cfg
      fn.screenInfo = {name: "T", width: s.screen[0], height: s.screen[1], virtualX: 0, virtualY: 0}
      logic.open = !!s.open
      tc.wait(350)
      var r = {pill: fn.pill, popup: fn.popup, pw: rect(fn.pillWindow), qw: rect(fn.popupWindow), available: fn.available, broken: fn.layerBroken,
               marker: logic.floatingActive}
      if (fn.useLayer && fn.available) { r.pl = layerOf(fn.pillWindow); r.ql = layerOf(fn.popupWindow) }
      grab(fn.pillWindow.contentItem, s.png ? s.png + "_pill.png" : "")
      if (s.open) grab(fn.popupWindow.contentItem, s.png ? s.png + "_popup.png" : "")
      %(drive)s
      result[s.name] = r
    }
    result.calls = logic.calls
    console.log("RESULT " + JSON.stringify(result)); Qt.quit()
  } }
}
"""


def run_floating(tmp_path, scenarios, layer=False, drive="", break_layer=False):
    imp = tmp_path / "imp"
    for rel, (qmldir, files) in {**POPUP_STUBS, "org/kde/plasma/plasmoid": PLASMOID_STUB, "org/kde/plasma/core": CORE_STUB}.items():
        d = imp / rel
        d.mkdir(parents=True)
        (d / "qmldir").write_text(qmldir)
        for f, body in files.items():
            (d / f).write_text(body)
    run = tmp_path / "run"
    run.mkdir()
    for f in FILES:
        shutil.copy(UI_DIR / f, run / f)
    if break_layer:
        (run / "FloatingLayer.qml").write_text("import QtQuick\nItem { this is not qml }")
    png_dir = os.environ.get("AIU_PNG_DIR", "")
    for s in scenarios:
        s["png"] = f"{png_dir}/{s['name']}" if png_dir else ""
    (run / "h.qml").write_text(HARNESS % {"data": json.dumps(fixture()), "layer": str(layer).lower(), "scenarios": json.dumps(scenarios), "drive": drive})
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", "-I", str(imp), str(run / "h.qml")], env=env, capture_output=True, text=True, timeout=120)
    out = res.stdout + res.stderr
    line = next((l for l in out.splitlines() if "RESULT " in l), None)
    assert line, out
    bad = [l for l in res.stderr.splitlines() if "TypeError" in l or "ReferenceError" in l or "Unable to assign" in l]
    assert not bad, bad[:3]
    return json.loads(line.split("RESULT ", 1)[1])


def sc(name, edge, size=100, off=0, screen=(1280, 720), open=True, **extra):
    cap = edge.capitalize()
    return {"name": name, "cfg": {"floatingNotch": True, "floatEdge": edge, "floatSize": size, f"floatOffset{cap}": off, **extra},
            "screen": list(screen), "open": open}


@needs_qml
@pytest.mark.parametrize("layer", [False, True], ids=["plain-window", "layer-shell-props"])
def test_four_edges_with_popup(tmp_path, layer):
    scenarios = [sc(f"{'ls' if layer else 'pl'}_{e}", e, off=-120 if e in ("top", "left") else 150) for e in EDGES]
    out = run_floating(tmp_path, scenarios, layer=layer)
    for s in scenarios:
        r = out[s["name"]]
        edge, (sw, sh) = s["cfg"]["floatEdge"], s["screen"]
        assert r["available"] is True and r["marker"] is True and r["pw"]["visible"] and r["qw"]["visible"]
        p, q = r["pill"], r["popup"]
        assert (p["x"], p["y"], p["w"], p["h"]) == (r["pw"]["x"], r["pw"]["y"], r["pw"]["w"], r["pw"]["h"])
        assert q["x"] >= 0 and q["y"] >= 0 and q["x"] + q["w"] <= sw and q["y"] + q["h"] <= sh
        assert (p["y"] == 4 if edge == "top" else p["y"] + p["h"] == sh - 4 if edge == "bottom"
                else p["x"] == 4 if edge == "left" else p["x"] + p["w"] == sw - 4)
        if layer:  # propriedades anexadas do layer-shell, lidas de volta: âncora sup-esq + margens = posição, zona exclusiva -1
            assert r["pl"]["anchors"] == 5 and r["pl"]["ez"] == -1 and (r["pl"]["ml"], r["pl"]["mt"]) == (p["x"], p["y"])
            assert r["ql"]["ez"] == -1 and (r["ql"]["ml"], r["ql"]["mt"]) == (q["x"], q["y"]) and r["ql"]["layer"] == 3
            assert r["pl"]["layer"] == 2 and r["pl"]["scope"] == "ai-usage-notch"


@needs_qml
def test_without_the_layer_module_the_floating_notch_is_unavailable(tmp_path):
    out = run_floating(tmp_path, [sc("broken", "top")], layer=True, break_layer=True)["broken"]
    assert out["broken"] is True and out["available"] is False and out["marker"] is False  # pílula segue no painel
    assert out["pw"]["visible"] is False


@needs_qml
def test_position_is_per_edge_and_reclamped_on_a_smaller_screen(tmp_path):
    cfg = {"floatingNotch": True, "floatOffsetTop": 400, "floatOffsetBottom": -200, "floatOffsetLeft": 100, "floatOffsetRight": 0}
    scenarios = [{"name": e, "cfg": {**cfg, "floatEdge": e}, "screen": [1280, 720], "open": False} for e in EDGES]
    scenarios.append({"name": "small", "cfg": {**cfg, "floatEdge": "top"}, "screen": [640, 360], "open": False})
    out = run_floating(tmp_path, scenarios)
    cx = lambda r: r["x"] + r["w"] / 2
    assert abs(cx(out["top"]["pill"]) - (640 + 400)) <= 1 and abs(cx(out["bottom"]["pill"]) - (640 - 200)) <= 1
    assert abs(out["left"]["pill"]["y"] + out["left"]["pill"]["h"] / 2 - (360 + 100)) <= 1
    p = out["small"]["pill"]
    assert 0 <= p["x"] and p["x"] + p["w"] <= 640  # 400 px do centro não cabe: reposiciona dentro da tela


@needs_qml
def test_drag_commits_once_snaps_and_recenters(tmp_path):
    drive = """
    if (s.name === "drag") {
      // o stub não notifica mudança de chave (o Plasmoid.configuration real sim): reatribuir imita a notificação
      var touch = function () { Plasmoid.configuration = Object.assign({}, Plasmoid.configuration); tc.wait(20) }
      fn.dragBy(50); fn.dragBy(60); r.live = fn.liveOffset; r.cfgDuring = Plasmoid.configuration.floatOffsetTop
      fn.dragEnd(); touch(); r.committed = Plasmoid.configuration.floatOffsetTop; r.liveAfter = isNaN(fn.liveOffset)
      fn.dragBy(-105); fn.dragEnd(); touch(); r.snapped = Plasmoid.configuration.floatOffsetTop
      fn.nudge(8); touch(); r.nudged = Plasmoid.configuration.floatOffsetTop
      fn.dragBy(900000); fn.dragEnd(); touch(); r.clamped = Plasmoid.configuration.floatOffsetTop
      fn.recenter(); touch(); r.recentered = Plasmoid.configuration.floatOffsetTop
      r.otherEdges = [Plasmoid.configuration.floatOffsetBottom, Plasmoid.configuration.floatOffsetLeft]
    }
    """
    out = run_floating(tmp_path, [{"name": "drag", "cfg": {"floatingNotch": True, "floatEdge": "top"}, "screen": [1280, 720], "open": False}], drive=drive)["drag"]
    assert out["live"] == 110 and "cfgDuring" not in out  # durante o arraste a configuração não é tocada
    assert out["committed"] == 110 and out["liveAfter"] is True
    assert out["snapped"] == 0  # 110 - 105 = 5, dentro de 12 px do centro
    assert out["nudged"] == 8
    assert 0 < out["clamped"] <= 640  # limitado ao comprimento da borda
    assert out["recentered"] == 0 and out["otherEdges"] == [None, None]


@needs_qml
def test_keyboard_and_pointer_reach_the_shared_pill(tmp_path):
    drive = """
    if (s.name === "keys") {
      var item = fn.pillWindow.contentItem
      tc.mouseClick(item, 20, 12); tc.wait(50)
    }
    """
    out = run_floating(tmp_path, [{"name": "keys", "cfg": {"floatingNotch": True, "floatEdge": "bottom"}, "screen": [1280, 720], "open": False}], drive=drive)
    assert "click" in out["calls"]  # o clique chega ao mesmo pillClicked do painel (abre/fixa/solta do ticket 34)
