"""Notch flutuante em varios monitores, de verdade: kwin_wayland --virtual com 2 saidas, layer-shell-qt real e o
FloatingNotch.qml real num "painel" (janela layer-shell) de uma das telas. Mede no protocolo (WAYLAND_DEBUG) em
qual wl_output cada get_layer_surface foi pedido. Pula sem kwin_wayland, dbus-run-session ou o modulo layer-shell.

NÃO coberto: o plasmashell real (painel de verdade), escalas fracionarias e hotplug de monitor.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from test_plasmoid_floating import CORE_STUB, FILES, HARNESS, PLASMOID_STUB, POPUP_STUBS, UI_DIR
from test_plasmoid_popup import fixture

LS_QML = Path("/usr/lib/qt6/qml/org/kde/layershell")
needs_wayland = pytest.mark.skipif(
    not all(shutil.which(b) for b in ("kwin_wayland", "dbus-run-session", "qml6")) or not LS_QML.exists(),
    reason="kwin_wayland/dbus-run-session/qml6/layer-shell-qt not available")

# Janela layer-shell = o painel do Plasma, na tela `hostScreen`; o FloatingNotch mora dentro dela (Window.window)
HOST = """
import QtQuick
import QtQuick.Window
import QtTest
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.layershell as LS
import "NotchModel.js" as NotchModel
import "I18n.js" as I18n
Window { id: win; width: 300; height: 40; color: "transparent"; flags: Qt.FramelessWindowHint | Qt.Tool
  property var scr: { var s = Qt.application.screens; for (var i = 0; i < s.length; i++) if (s[i].name === "%(host)s") return s[i]; return null }
  screen: scr
  x: scr.virtualX + 20; y: scr.virtualY + 20
  Component.onCompleted: {
    var a = win.LS.Window; a.scope = "host-panel"; a.layer = LS.Window.LayerTop; a.exclusionZone = -1
    a.anchors = LS.Window.AnchorTop | LS.Window.AnchorLeft; a.margins.left = 20; a.margins.top = 20
    visible = true
  }
"""
TAIL = """
  property var result: ({})
  Timer { interval: 400; running: true; onTriggered: {
    Plasmoid.configuration = %(cfg)s
    tc.wait(600)
    var w = fn.pillWindow
    console.log("RESULT " + JSON.stringify({names: Qt.application.screens.map(function (s) { return s.name }), wsn: fn.widgetScreenName,
      idx: fn.screenIdx, available: fn.available, pillScreen: w.screen ? w.screen.name : "", visible: w.visible, x: w.x, y: w.y, lx: w.x - fn.screenInfo.virtualX, ly: w.y - fn.screenInfo.virtualY, w: w.width, h: w.height, scr: fn.scrRect}))
    Qt.quit()
  } }
}
"""


def _harness(host, cfg, late):
    body = HARNESS.split("Window { id: win; visible: true; width: 20; height: 20\n", 1)[1].split("  property var result", 1)[0]
    body = body % {"data": json.dumps(fixture()), "layer": "true"}
    if late == "orphan":  # medido no plasmashell real: o item nunca entra numa janela; so containment.screenGeometry diz a tela
        body = body.replace("FloatingNotch { id: fn;", "FloatingNotch { id: fn; parent: null;")
    elif late:  # o widget so entra na janela do painel depois de criado (Window.window nulo no inicio), como no Plasma
        body = body.replace("FloatingNotch { id: fn;", "FloatingNotch { id: fn; parent: win.attached ? win.contentItem : null;")
        body = "  property bool attached: false\n  Timer { interval: 300; running: true; onTriggered: win.attached = true }\n" + body
    return (HOST % {"host": host}) + body + (TAIL % {"cfg": json.dumps(cfg)})


@pytest.fixture(scope="module")
def kwin(tmp_path_factory):
    rt = tmp_path_factory.mktemp("xdg")
    rt.chmod(0o700)
    env = dict(os.environ, XDG_RUNTIME_DIR=str(rt), QT_QPA_PLATFORM="offscreen")
    p = subprocess.Popen(["dbus-run-session", "--", "kwin_wayland", "--virtual", "--socket", "wl-test", "--width", "2560", "--height", "1440",
                          "--output-count", "2", "--no-lockscreen", "--no-global-shortcuts"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if (rt / "wl-test").exists():
            break
        time.sleep(0.1)
    else:
        p.terminate()
        pytest.skip("kwin_wayland --virtual nao subiu")
    time.sleep(0.5)
    yield rt
    p.terminate()
    p.wait(timeout=10)


def run_wayland(kwin, tmp_path, host, cfg, late=False):
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
    if late == "orphan":
        x = 2560 if host == "Virtual-1" else 0
        pl = imp / "org/kde/plasma/plasmoid/Plasmoid.qml"
        pl.write_text(pl.read_text().replace("property var configuration:", "property var containment: ({screenGeometry: {x: %d, y: 0, width: 2560, height: 1440}})\n property var configuration:" % x))
    (run / "h.qml").write_text(_harness(host, cfg, late))
    env = dict(os.environ, XDG_RUNTIME_DIR=str(kwin), WAYLAND_DISPLAY="wl-test", QT_QPA_PLATFORM="wayland",
               QT_FORCE_STDERR_LOGGING="1", WAYLAND_DEBUG="1", QT_QUICK_CONTROLS_STYLE="Basic")
    res = subprocess.run(["qml6", "-I", str(imp), str(run / "h.qml")], env=env, capture_output=True, text=True, timeout=120)
    out = res.stdout + res.stderr
    line = next((l for l in out.splitlines() if "RESULT " in l), None)
    assert line, out[-2000:]
    result = json.loads(line.split("RESULT ", 1)[1])
    names = {}   # wl_output#N -> nome
    for m in re.finditer(r"wl_output#(\d+)\.name\(\"([^\"]+)\"\)", out):
        names[m.group(1)] = m.group(2)
    layers = {}  # scope -> nome do output pedido
    for m in re.finditer(r'get_layer_surface\(new id [^,]+, wl_surface#\d+, (wl_output#(\d+)|nil), \d+, "([^"]+)"\)', out):
        layers[m.group(3)] = names.get(m.group(2), "compositor") if m.group(2) else "compositor"
    result["layers"] = layers
    return result


@needs_wayland
@pytest.mark.parametrize("host", ["Virtual-0", "Virtual-1"])
def test_notch_goes_to_the_screen_of_the_widget(kwin, tmp_path, host):
    r = run_wayland(kwin, tmp_path, host, {"floatingNotch": True})
    assert r["layers"]["host-panel"] == host  # a premissa do cenario: o "painel" esta na tela pedida
    assert r["layers"]["ai-usage-notch"] == host, r


@needs_wayland
@pytest.mark.parametrize("host", ["Virtual-0", "Virtual-1"])
def test_notch_goes_to_the_widget_screen_even_if_the_widget_joins_its_window_late(kwin, tmp_path, host):
    r = run_wayland(kwin, tmp_path, host, {"floatingNotch": True}, late=True)
    assert r["layers"]["ai-usage-notch"] == host, r


@needs_wayland
@pytest.mark.parametrize("host", ["Virtual-0", "Virtual-1"])
def test_notch_uses_the_containment_screen_when_the_item_has_no_window(kwin, tmp_path, host):
    """Causa raiz do bug: Window.window nulo no plasmashell real => indice 0 do Qt, mesmo com o painel na 2a tela."""
    r = run_wayland(kwin, tmp_path, host, {"floatingNotch": True}, late="orphan")
    assert r["wsn"] == host and r["layers"]["ai-usage-notch"] == host, r


def test_screen_name_at_matches_by_corner(tmp_path):
    from test_plasmoid_floating import js
    scr = '[{name: "A", virtualX: 2560, virtualY: 0}, {name: "B", virtualX: 0, virtualY: 0}]'
    assert js(tmp_path, 'FG.screenNameAt(%s, {x: 0, y: 0})' % scr) == "B"
    assert js(tmp_path, '[FG.screenNameAt(%s, {x: 5, y: 0}), FG.screenNameAt(%s, null), FG.screenNameAt([], {x: 0, y: 0})]' % (scr, scr)) == ["", "", ""]


@needs_wayland
@pytest.mark.parametrize("host,chosen,floats", [("Virtual-0", "Virtual-0", True), ("Virtual-1", "Virtual-1", True),
                                                ("Virtual-0", "Virtual-1", False), ("Virtual-1", "Virtual-0", False)])
def test_float_screen_only_the_instance_on_that_screen_floats(kwin, tmp_path, host, chosen, floats):
    r = run_wayland(kwin, tmp_path, host, {"floatingNotch": True, "floatScreen": chosen}, late="orphan")
    assert r["available"] is floats and r["visible"] is floats, r  # regra mantida (ADR-0010): a de outra tela fica como pilula no painel
    if floats:
        assert r["layers"]["ai-usage-notch"] == chosen, r


@needs_wayland
@pytest.mark.parametrize("edge", ["top", "bottom", "left", "right"])
@pytest.mark.parametrize("host", ["Virtual-0", "Virtual-1"])
def test_notch_at_400_percent_stays_inside_the_real_screen(kwin, tmp_path, host, edge):
    (tmp_path / "base").mkdir()
    r = run_wayland(kwin, tmp_path, host, {"floatingNotch": True, "floatSize": 400, "floatEdge": edge})
    sw, sh = r["scr"]["w"], r["scr"]["h"]
    assert r["available"] and r["visible"] and r["layers"]["ai-usage-notch"] == host, r
    assert r["lx"] >= 0 and r["ly"] >= 0 and r["lx"] + r["w"] <= sw and r["ly"] + r["h"] <= sh, r  # coordenadas locais a tela
    base = run_wayland(kwin, tmp_path / "base", host, {"floatingNotch": True, "floatEdge": edge})
    cross = "w" if edge in ("left", "right") else "h"
    assert r[cross] > 2 * base[cross], (r, base)  # a escala 400% foi mesmo aplicada
