"""main.qml real (qml6 offscreen, stubs do Plasma): hover abre, fixa/solta com clique, dica com limites."""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_usage_collector.contract import build_agent_account_status
from test_plasmoid_notch_render import COMPACT_FILES, STUBS, UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")

PLASMOID = ("module org.kde.plasma.plasmoid\nsingleton Plasmoid 1.0 Plasmoid.qml\nPlasmoidItem 1.0 PlasmoidItem.qml\n", {
    "Plasmoid.qml": "pragma Singleton\nimport QtQuick\nQtObject { property int formFactor: 2; property string title: ''\n"
                    " property var configuration: ({providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: true}) }",
    "PlasmoidItem.qml": "import QtQuick\nItem { property bool expanded: false; property string toolTipMainText; property string toolTipSubText\n"
                        " property int toolTipTextFormat: -1; property bool hideOnWindowDeactivate: true; property var preferredRepresentation\n"
                        " property var compactRepresentation; property var fullRepresentation }"})
EXTRA = {
    "org/kde/plasma/plasma5support": ("module org.kde.plasma.plasma5support\nDataSource 1.0 DataSource.qml\n", {
        "DataSource.qml": "import QtQuick\nQtObject { property string engine; property var connectedSources: []\n"
                          " signal newData(string s, var d); function connectSource(s) {} function disconnectSource(s) {} }"}),
}


def iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


def fixture():
    claude = build_agent_account_status(
        provider="claude", account_id="a", label="A", source="auto", health={"status": "session_expired"}, is_active=True,
        native_window={"usage_percentage": 40.0, "release_time": iso(timedelta(hours=2, minutes=30, seconds=30)), "window_seconds": 18000},
        weekly_window=None)
    codex = build_agent_account_status(
        provider="codex", account_id="b", label="B", source="auto", health={"status": "valid"}, is_active=True,
        native_window={"usage_percentage": 10.0, "release_time": iso(-timedelta(minutes=5)), "window_seconds": 18000},
        weekly_window={"usage_percentage": 70.0, "cycle_reset_time": iso(timedelta(days=3, hours=5, minutes=30)), "window_seconds": 604800})
    codex["limit_changes"] = [{"kind": "x"}]
    gemini = build_agent_account_status(provider="gemini", account_id="g", label="G", source="auto", health={"status": "valid"}, is_active=True)
    gemini["stale"] = True
    return {"agents": {"claude": {"name": "Claude", "accounts": [claude]}, "codex": {"name": "Codex", "accounts": [codex]},
                       "gemini": {"name": "Gemini", "accounts": [gemini]}}}


# Passos: (espera em ms antes, JS). `m` = main.qml, `Plasmoid`, `obs(k, v)` registra.
STEPS = [
    (0, "m.setPillHovered(true)"),
    (150, "obs('before300', m.expanded); obs('hovering', timers())"),
    (300, "obs('after300', m.expanded); obs('tooltip', m.toolTipSubText); obs('fmt', m.toolTipTextFormat); obs('opened', timers())"),
    (0, "m.setPillHovered(false)"),
    (100, "obs('grace', m.expanded); m.setPopupHovered(true)"),            # mouse transita para o popup
    (500, "obs('onPopup', m.expanded); m.setPopupHovered(false)"),
    (500, "obs('leftPopup', m.expanded); obs('idle', timers()); obs('pinnedReset', m.pinned)"),
    (0, "m.setPillHovered(true)"),
    (400, "obs('reopen', m.expanded); m.pillClicked(); obs('pinned', m.pinned); m.setPillHovered(false)"),
    (500, "obs('pinnedStays', m.expanded); m.setPillHovered(true); m.pillClicked(); obs('unpinned', m.pinned); obs('deactHover', m.hideOnWindowDeactivate); m.setPillHovered(false)"),
    (500, "obs('closedAfterUnpin', m.expanded); obs('deactIdle', m.hideOnWindowDeactivate)"),
    # pinned com o mouse fora: soltar pelo teclado/acessibilidade arma o fechamento
    (0, "m.setPillHovered(true)"),
    (400, "m.pillClicked(); m.setPillHovered(false)"),
    (400, "obs('pinnedAway', m.expanded); m.pillClicked()"),
    (500, "obs('unpinnedAway', m.expanded)"),
    # popup aberto por atalho/ação externa: o mouse passar pela pílula não o fecha
    (0, "m.expanded = true; m.setPillHovered(true); m.setPillHovered(false)"),
    (500, "obs('external', m.expanded); m.expanded = false"),
    # desligar a opção com o timer de abertura pendente
    (0, "m.setPillHovered(true); Plasmoid.configuration = {providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: false}"),
    (450, "obs('offPending', m.expanded); m.setPillHovered(false); Plasmoid.configuration = {providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: true}"),
    # desligar com o popup aberto por hover e o timer de saída pendente
    (0, "m.setPillHovered(true)"),
    (400, "m.setPillHovered(false); Plasmoid.configuration = {providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: false}"),
    (500, "obs('offClose', m.expanded); m.expanded = false"),
    (0, "Plasmoid.configuration = {providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: false}; m.setPillHovered(true)"),
    (450, "obs('clickOnlyHover', m.expanded); m.pillClicked(); obs('clickOnlyOpen', m.expanded); m.setPillHovered(false)"),
    (500, "obs('clickOnlyStays', m.expanded); m.pillClicked(); obs('clickOnlyClosed', m.expanded)"),
    # ticket 48: o clique num item destaca o provedor; o hover nunca destaca
    (0, "Plasmoid.configuration = {providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: true}; m.setPillHovered(true)"),
    (400, "obs('hoverHl', [m.expanded, m.highlightProvider]); m.pillClicked('codex'); obs('clickHl', m.highlightProvider); m.setPillHovered(false)"),
    (500, "obs('clickHlStays', [m.expanded, m.pinned, m.highlightProvider]); m.pillClicked('claude'); obs('unpinKeeps', m.highlightProvider); m.closePopup(); obs('closedHl', m.highlightProvider)"),
    (0, "m.pillClicked('gemini'); obs('openByClick', [m.expanded, m.highlightProvider]); m.closePopup(); m.pillClicked(); obs('noProvider', [m.expanded, m.highlightProvider]); m.closePopup()"),
    (0, "Plasmoid.configuration = {providerOrder: 'claude,codex,gemini', hiddenProviders: '', accentPreset: 'plasma', hoverOpen: false}; m.pillClicked('codex'); obs('clickOnlyHl', [m.expanded, m.highlightProvider]); m.pillClicked('codex'); obs('clickOnlyCloseHl', [m.expanded, m.highlightProvider])"),
    (0, "m.pillClicked('claude'); m.expanded = false; obs('externalCloseHl', m.highlightProvider)"),
]

HARNESS = """
import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
Window { visible: true; width: 100; height: 40
  Main { id: m }
  property var out: ({})
  property int i: 0
  function obs(k, v) { out[k] = v }
  function timers() { var r = []; for (var j = 0; j < m.data.length; j++) { var o = m.data[j]; if (o.interval !== undefined && o.interval <= 1000 && o.running) r.push(o.interval) } return r.sort(function (a, b) { return a - b }) }
  property var steps: [%(steps)s]
  Timer { id: runner; repeat: false; onTriggered: { steps[i][1](); i++; next() } }
  function next() { if (i >= steps.length) { m.statusData = null; console.log("RESULT " + JSON.stringify(out)); Qt.quit() } else { runner.interval = Math.max(1, steps[i][0]); runner.start() } }
  Component.onCompleted: { m.statusData = %(data)s; next() }
}
"""


def run(tmp_path):
    imp = tmp_path / "imp"
    for rel, (qmldir, files) in {**STUBS, "org/kde/plasma/plasmoid": PLASMOID, **EXTRA}.items():
        d = imp / rel
        d.mkdir(parents=True)
        (d / "qmldir").write_text(qmldir)
        for f, body in files.items():
            (d / f).write_text(body)
    r = tmp_path / "run"
    r.mkdir()
    for f in COMPACT_FILES:
        shutil.copy(UI_DIR / f, r / f)
    (r / "FullRepresentation.qml").write_text("import QtQuick\nItem { property var plasmoidItem }")
    main = (UI_DIR / "main.qml").read_text()
    main = re.sub(r"\n\s*Plasmoid\.backgroundHints:.*?\n\n", "\n\n", main, flags=re.S)  # atribuição de attached não existe no stub
    main = re.sub(r"\n\s*Plasmoid\.(icon|title|status):[^\n]*", "", main)
    (r / "Main.qml").write_text(main)
    steps = ",".join("[%d, function () { %s }]" % (d, js) for d, js in STEPS)
    (r / "h.qml").write_text(HARNESS % {"steps": steps, "data": json.dumps(fixture())})
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", "-I", str(imp), str(r / "h.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next((l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l), None)
    assert line, res.stdout + res.stderr
    return json.loads(line.split("RESULT ", 1)[1])


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    return run(tmp_path_factory.mktemp("hover"))


def test_hover_opens_after_300ms_and_closes_on_leave_with_grace(out):
    assert out["before300"] is False and out["after300"] is True
    assert out["grace"] is True            # atraso de saída: não pisca
    assert out["onPopup"] is True          # mouse sobre o popup: não fecha
    assert out["leftPopup"] is False       # saiu do popup: fecha
    assert out["reopen"] is True


def test_click_pins_and_unpins(out):
    assert out["pinned"] is True and out["pinnedStays"] is True
    assert out["unpinned"] is False and out["closedAfterUnpin"] is False
    # M1: com o mouse na pílula o press não pode fechar o popup por perda de foco
    assert out["deactHover"] is False and out["deactIdle"] is True


def test_unpin_with_mouse_away_closes_and_external_open_is_left_alone(out):
    assert out["pinnedAway"] is True and out["unpinnedAway"] is False
    assert out["external"] is True


def test_disabling_hover_at_runtime_cancels_pending_timers(out):
    assert out["offPending"] is False and out["offClose"] is True


def test_click_only_option_disables_hover(out):
    assert out["clickOnlyHover"] is False and out["clickOnlyOpen"] is True
    assert out["clickOnlyStays"] is True and out["clickOnlyClosed"] is False


def test_no_orphan_timers_with_popup_closed(out):
    assert out["hovering"] == [300, 1000]  # espera de abertura + contagem da dica, só com o mouse na pílula
    assert out["opened"] == []             # popup aberto: nenhum timer de hover rodando
    assert out["idle"] == [] and out["pinnedReset"] is False


def test_tooltip_lists_all_limits_with_countdown(out):
    tip = out["tooltip"]
    assert out["fmt"] == 0  # Text.PlainText
    assert "Claude\n  Native window: 40% — releases in 2h 30min\n  Weekly: —" in tip
    assert "Codex\n  Native window: already released\n  Weekly: 70% — releases in 3d 5h" in tip
    # saúde / obsolescência / mudança de limites, curtas e em texto puro
    assert "Weekly: —\n  Session expired\nCodex" in tip
    assert "Weekly: 70% — releases in 3d 5h\n  limits changed\nGemini" in tip
    assert "Gemini\n  Native window: —\n  Weekly: —\n  stale data" in tip
    assert "0%" not in tip.replace("10%", "").replace("70%", "").replace("40%", "")


def test_click_highlights_the_provider_but_hover_never_does(out):
    assert out["hoverHl"] == [True, ""]                  # aberto por hover: ninguém destacado
    assert out["clickHl"] == "codex"                     # clique no item: destaca (popup já aberto por hover)
    assert out["clickHlStays"] == [True, True, "codex"]
    assert out["unpinKeeps"] == "codex"                  # soltar o fixado não troca o destaque
    assert out["closedHl"] == ""                         # fechar apaga: nunca persiste
    assert out["openByClick"] == [True, "gemini"]
    assert out["noProvider"] == [True, ""]               # clique sem item (teclado/fatia): abre sem destacar
    assert out["clickOnlyHl"] == [True, "codex"] and out["clickOnlyCloseHl"] == [False, ""]
    assert out["externalCloseHl"] == ""


def test_highlight_is_not_persisted_in_config():
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    assert "highlightProvider" in main and "Plasmoid.configuration.highlightProvider" not in main
    assert "highlightProvider" not in (UI_DIR.parent / "config" / "main.xml").read_text(encoding="utf-8")
