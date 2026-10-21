"""Notch compacto rodando de verdade em qml6 offscreen, com stubs de Kirigami/Plasmoid (opcional)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_usage_collector.contract import build_agent_account_status

UI_DIR = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui"
pytestmark = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")

STUBS = {
    "org/kde/kirigami": ("module org.kde.kirigami\nsingleton Units 1.0 Units.qml\nsingleton Theme 1.0 Theme.qml\n", {
        "Units.qml": "pragma Singleton\nimport QtQuick\nQtObject { property var iconSizes: ({small:16, smallMedium:22, medium:32}); property int smallSpacing: 4; property int gridUnit: 18 }",
        "Theme.qml": "pragma Singleton\nimport QtQuick\nQtObject { property color highlightColor: '#3daee9'; property color highlightedTextColor: '#ffffff'; property var smallFont: ({pointSize: 9}) }"}),
    "org/kde/plasma/plasmoid": ("module org.kde.plasma.plasmoid\nsingleton Plasmoid 1.0 Plasmoid.qml\n", {
        "Plasmoid.qml": "pragma Singleton\nimport QtQuick\nQtObject { property int formFactor: 2 }"}),
    "org/kde/plasma/core": ("module org.kde.plasma.core\nsingleton Types 1.0 Types.qml\n", {
        "Types.qml": "pragma Singleton\nimport QtQuick\nQtObject { enum FormFactor { Planar = 0, Horizontal = 2, Vertical = 3 } }"}),
}

HARNESS = """
import QtQuick
import QtQuick.Window
import QtTest
import org.kde.plasma.plasmoid
import "NotchModel.js" as NotchModel
Window { visible: true; width: %(w)d; height: %(h)d; color: "#303236"
  Item { id: logic
    property var compactModel: NotchModel.buildModel(%(data)s, %(cfg)s, safeI18n)
    property string worstHealthStatus: NotchModel.worstHealth(compactModel)
    property var updateInfo: NotchModel.updateSummary(%(data)s, safeI18n)
    property int totalInvites: %(invites)d
    property color accentColor: "#3daee9"
    property string toolTipMainText: "AI"
    property string toolTipSubText: ""
    property bool expanded: false
    property var calls: []
    function setPillHovered(h) { calls.push("hover:" + h) }
    function pillClicked() { calls.push("click") }
    function closePopup() { calls.push("close") }
    function safeI18n(t, a, b) { var r = t; if (a !== undefined) r = r.replace("%%1", a); if (b !== undefined) r = r.replace("%%2", b); return r }
  }
  CompactRepresentation { id: c; plasmoidItem: logic; anchors.fill: parent }
  property bool skipGrab: false
  Timer { id: fin; interval: 100; onTriggered: { console.log("RESULT " + JSON.stringify({calls: logic.calls})); Qt.quit() } }
  TestCase { id: tc; when: false }
  Component.onCompleted: Plasmoid.formFactor = %(ff)d
  Timer { interval: 600; running: true; onTriggered: {
    %(drive)s
    if (skipGrab) { fin.start(); return }
    c.grabToImage(function (r) {
      if ("%(png)s") r.saveToFile("%(png)s");
      console.log("RESULT " + JSON.stringify({model: logic.compactModel, health: logic.worstHealthStatus, update: logic.updateInfo, calls: logic.calls}));
      Qt.quit() }) } }
}
"""


def render(tmp_path, name, agents, vertical=False, invites=0, hidden="", drive="", extra_cfg=None, updates=None):
    imp = tmp_path / "imp"
    for rel, (qmldir, files) in STUBS.items():
        d = imp / rel
        d.mkdir(parents=True)
        (d / "qmldir").write_text(qmldir)
        for f, body in files.items():
            (d / f).write_text(body)
    run = tmp_path / "run"
    run.mkdir()
    for f in ("CompactRepresentation.qml", "DualRing.qml", "Presets.js", "NotchModel.js"):
        shutil.copy(UI_DIR / f, run / f)
    png_dir = os.environ.get("AIU_PNG_DIR", "")
    cfg = {"providerOrder": "claude,codex,gemini", "hiddenProviders": hidden, **(extra_cfg or {})}
    (run / "h.qml").write_text(HARNESS % {
        "w": 40 if vertical else 300, "h": 160 if vertical else 40, "data": json.dumps({"agents": agents, "updates": updates}),
        "cfg": json.dumps(cfg), "invites": invites, "ff": 3 if vertical else 2,
        "png": f"{png_dir}/{name}.png" if png_dir else "", "drive": drive})
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", "-I", str(imp), str(run / "h.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next((l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l), None)
    assert line, res.stdout + res.stderr
    return json.loads(line.split("RESULT ", 1)[1])


def acct(active, weekly=None, health="valid"):
    return build_agent_account_status(
        provider="claude", account_id="a", label="A", source="auto", health={"status": health}, is_active=active,
        native_window={"usage_percentage": 40.0, "release_time": "2099-01-01T00:00:00+00:00", "window_seconds": 18000},
        weekly_window=weekly,
    )


def test_missing_weekly_window_is_unknown_not_zero(tmp_path):
    out = render(tmp_path, "a1", {"claude": {"name": "Claude", "accounts": [acct(True, weekly=None)]}}, invites=2)
    claude = out["model"][0]
    assert claude["outerPct"] == -1 and claude["innerPct"] == 40
    assert "semanal -" in claude["description"] and "0%" not in claude["description"].replace("40%", "")


def test_no_active_account_shows_neutral_provider_without_health_badge(tmp_path):
    agents = {"claude": {"name": "Claude", "accounts": [acct(False, health="session_expired")]}}
    out = render(tmp_path, "m1", agents, vertical=True)
    claude = out["model"][0]
    assert claude["innerPct"] == -1 and claude["outerPct"] == -1
    assert "sem conta ativa" in claude["description"]
    assert out["health"] == ""


def test_update_badge_model_ignores_untrusted_values(tmp_path):
    ok = "https://github.com/victorlcs87/plasma-ai-usage-widget/releases/tag/v9.0.0"
    items = {"widget": {"latest": "9.0.0", "available": True, "url": "https://evil.example/x"},
             "claude": {"latest": "2.1.0", "available": True}, "codex": {"latest": "1.0.0", "available": False},
             "gemini": {"latest": 5, "available": True}}
    agents = {"claude": {"name": "Claude", "accounts": [acct(True)]}}
    out = render(tmp_path, "u1", agents, updates={"enabled": True, "items": items})
    info = out["update"]
    assert info["widget"]["url"] == "" and info["clis"] == ["claude"]
    assert [l["text"] for l in info["lines"]] == ["Nova versão do widget: 9.0.0", "Nova versão do Claude Code: 2.1.0"]
    assert out["model"][0]["update"]["latest"] == "2.1.0" and "nova versão 2.1.0" in out["model"][0]["description"]
    items["widget"]["url"] = ok
    assert render(tmp_path / "b", "u2", agents, updates={"enabled": True, "items": items})["update"]["widget"]["url"] == ok
    for n, bad in enumerate((ok + "/../../x", ok + "/%2E%2e/x", ok + "..%2fx", ok + "%5Cx", ok + "%zz",
                             "https://github.com/victorlcs87/plasma-ai-usage-widget/tree/main")):
        items["widget"]["url"] = bad
        got = render(tmp_path / f"c{n}", f"u3{n}", agents, updates={"enabled": True, "items": items})
        assert got["update"]["widget"]["url"] == "", bad


def test_session_state_in_model_and_rings_render(tmp_path):
    for n in ("busy", "waiting", "off", "bad"):
        (tmp_path / n).mkdir()
    agents = {"claude": {"name": "Claude", "accounts": [acct(True)]}}
    for state, word in (("busy", "ocupada"), ("waiting", "aguardando")):
        out = render(tmp_path / state, f"s_{state}", agents, extra_cfg={"showSession": True, "sessionOverlay": {"a": state}})
        assert out["model"][0]["sessionState"] == state and word in out["model"][0]["description"]
    off = render(tmp_path / "off", "s_off", agents, extra_cfg={"sessionOverlay": {"a": "busy"}})  # desligado: sem indicador
    assert off["model"][0]["sessionState"] == ""
    bogus = render(tmp_path / "bad", "s_bad", agents, extra_cfg={"showSession": True, "sessionOverlay": {"a": "<b>x</b>"}})
    assert bogus["model"][0]["sessionState"] == ""


def test_pill_forwards_mouse_and_escape_to_popup_logic(tmp_path):
    """Eventos sintéticos (QtTest): hover/clique vão para a lógica do popup; Escape fecha."""
    drive = """
    tc.mouseMove(c, 20, 20);
    tc.mouseClick(c, 20, 20);
    c.forceActiveFocus();
    tc.keyClick(Qt.Key_Escape);
    """
    agents = {"claude": {"name": "Claude", "accounts": [acct(True)]}}
    assert render(tmp_path, "h1", agents, drive=drive)["calls"] == ["hover:true", "click", "close"]


def test_destroying_pill_with_mouse_over_releases_hover(tmp_path):
    """M2: representação destruída com o mouse em cima não deixa pillHovered preso."""
    agents = {"claude": {"name": "Claude", "accounts": [acct(True)]}}
    out = render(tmp_path, "h2", agents, drive="tc.mouseMove(c, 20, 20); c.destroy(); skipGrab = true;")
    assert out["calls"] == ["hover:true", "hover:false"]


def test_session_animations_stop_when_hidden_by_idle(tmp_path):
    """Widget oculto por ociosidade (active: false) ou janela oculta: nenhuma animacao roda."""
    (tmp_path / "imp").mkdir()
    shutil.copy(UI_DIR / "DualRing.qml", tmp_path / "DualRing.qml")
    (tmp_path / "h.qml").write_text("""
import QtQuick
import QtQuick.Window
Window { visible: true; width: 40; height: 40
  DualRing { id: a; anchors.fill: parent; sessionState: "busy"; active: true }
  DualRing { id: b; width: 20; height: 20; sessionState: "waiting"; active: false }
  Timer { interval: 300; running: true; onTriggered: { console.log("RESULT " + JSON.stringify([a.shown, b.shown])); Qt.quit() } }
}""")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", str(tmp_path / "h.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next(l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l)
    assert json.loads(line.split("RESULT ", 1)[1]) == [True, False]


def test_update_marks_meet_contrast_for_any_highlight(tmp_path):
    """Selo e ponto de atualização: >= 4,5:1 sobre a pílula (#15171b) mesmo com realce escuro ou claro demais."""
    (tmp_path / "p").mkdir()
    shutil.copy(UI_DIR / "Presets.js", tmp_path / "p" / "Presets.js")
    colors = ["#3daee9", "#2980b9", "#1d3557", "#000000", "#ffffff", "#8e44ad", "#16a085"]
    (tmp_path / "p" / "t.qml").write_text("""
import QtQuick
import "Presets.js" as P
Item { Component.onCompleted: {
  var out = %s.map(function (h) { var c = Qt.color(h); return P.onPill(c.r, c.g, c.b) });
  console.log("RESULT " + JSON.stringify(out)); Qt.quit() } }
""" % json.dumps(colors))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", str(tmp_path / "p" / "t.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next(l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l)
    out = json.loads(line.split("RESULT ", 1)[1])

    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    for given, got in zip(colors, out):
        assert (lum(got) + 0.05) / (lum("#15171b") + 0.05) >= 4.5, (given, got)  # glifo (#15171b) e forma
    assert out[0] == "#3daee9"  # Breeze ja passa: cor preservada
