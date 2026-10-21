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
        "Theme.qml": "pragma Singleton\nimport QtQuick\nQtObject { property color highlightColor: '#3daee9'; property var smallFont: ({pointSize: 9}) }"}),
    "org/kde/plasma/plasmoid": ("module org.kde.plasma.plasmoid\nsingleton Plasmoid 1.0 Plasmoid.qml\n", {
        "Plasmoid.qml": "pragma Singleton\nimport QtQuick\nQtObject { property int formFactor: 2 }"}),
    "org/kde/plasma/core": ("module org.kde.plasma.core\nsingleton Types 1.0 Types.qml\n", {
        "Types.qml": "pragma Singleton\nimport QtQuick\nQtObject { enum FormFactor { Planar = 0, Horizontal = 2, Vertical = 3 } }"}),
}

HARNESS = """
import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
import "NotchModel.js" as NotchModel
Window { visible: true; width: %(w)d; height: %(h)d; color: "#303236"
  Item { id: logic
    property var compactModel: NotchModel.buildModel(%(data)s, %(cfg)s, safeI18n)
    property string worstHealthStatus: NotchModel.worstHealth(compactModel)
    property int totalInvites: %(invites)d
    property color accentColor: "#3daee9"
    property string toolTipMainText: "AI"
    property string toolTipSubText: ""
    property bool expanded: false
    function safeI18n(t, a, b) { var r = t; if (a !== undefined) r = r.replace("%%1", a); if (b !== undefined) r = r.replace("%%2", b); return r }
  }
  CompactRepresentation { id: c; plasmoidItem: logic; anchors.fill: parent }
  Component.onCompleted: Plasmoid.formFactor = %(ff)d
  Timer { interval: 600; running: true; onTriggered: {
    c.grabToImage(function (r) {
      if ("%(png)s") r.saveToFile("%(png)s");
      console.log("RESULT " + JSON.stringify({model: logic.compactModel, health: logic.worstHealthStatus}));
      Qt.quit() }) } }
}
"""


def render(tmp_path, name, agents, vertical=False, invites=0, hidden=""):
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
    cfg = {"providerOrder": "claude,codex,gemini", "hiddenProviders": hidden}
    (run / "h.qml").write_text(HARNESS % {
        "w": 40 if vertical else 300, "h": 160 if vertical else 40, "data": json.dumps({"agents": agents}),
        "cfg": json.dumps(cfg), "invites": invites, "ff": 3 if vertical else 2,
        "png": f"{png_dir}/{name}.png" if png_dir else ""})
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
