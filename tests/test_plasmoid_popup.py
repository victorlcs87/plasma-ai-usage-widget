"""Popup Notch (ticket 33) rodando de verdade em qml6 offscreen, com stubs do Plasma (opcional).

Nenhum comando é executado: o stub de DataSource só registra o que seria rodado. Dados só de fixtures.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_usage_collector.contract import build_agent_account_status

UI_DIR = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui"
pytestmark = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")

STUBS = {
    "org/kde/kirigami": ("module org.kde.kirigami\nsingleton Units 1.0 Units.qml\nsingleton Theme 1.0 Theme.qml\nIcon 1.0 Icon.qml\n", {
        "Units.qml": "pragma Singleton\nimport QtQuick\nQtObject { property var iconSizes: ({small:16, smallMedium:22, medium:32}); property int smallSpacing: 4;"
                     " property int gridUnit: 18; property int longDuration: 200 }",
        "Theme.qml": "pragma Singleton\nimport QtQuick\nQtObject { property color highlightColor: '#3daee9'; property color highlightedTextColor: '#ffffff';"
                     " property var smallFont: ({pointSize: 9}); property var defaultFont: ({pointSize: 10}) }",
        "Icon.qml": "import QtQuick\nRectangle { property string source; property color color: 'white'; implicitWidth: 16; implicitHeight: 16; radius: 3; opacity: 0.6 }"}),
    "org/kde/plasma/plasmoid": ("module org.kde.plasma.plasmoid\nsingleton Plasmoid 1.0 Plasmoid.qml\n", {
        "Plasmoid.qml": "pragma Singleton\nimport QtQuick\nQtObject { property int formFactor: 0; property var triggered: []\n"
                        " function internalAction(n) { return { trigger: function () { triggered.push(n) } } }\n"
                        " property var configuration: QtObject { property var usageDisplay: 'used'; property var resetDisplay: 'countdown'\n"
                        "  property var popupOpacity: 100; property var popupProviderOrder: 'claude,codex,gemini'; property var popupHiddenProviders: ''\n"
                        "  property var sessionState: false } }"}),
    "org/kde/plasma/plasma5support": ("module org.kde.plasma.plasma5support\nDataSource 1.0 DataSource.qml\nsingleton Log 1.0 Log.qml\n", {
        "Log.qml": "pragma Singleton\nimport QtQuick\nQtObject { property var cmds: []; property var sources: [] }",
        "DataSource.qml": "import QtQuick\nQtObject { property string engine; property var connectedSources: []\n"
                          " signal newData(string s, var d); function connectSource(s) { Log.cmds.push(s) } function disconnectSource(s) {}\n"
                          " Component.onCompleted: Log.sources.push(this) }"}),
}

FILES = ("FullRepresentation.qml", "AccountCard.qml", "WindowRow.qml", "NotchButton.qml", "PlainTip.qml", "UsageDetails.qml", "TokenHistory.qml",
         "DualRing.qml", "SessionMark.qml", "Presets.js", "I18n.js", "Collector.js", "NotchModel.js", "PanelStyle.js", "ViewPrefs.js")

HARNESS = """
import QtQuick
import QtQuick.Window
import QtTest
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support
import org.kde.kirigami as Kirigami
import "NotchModel.js" as NotchModel
import "I18n.js" as I18n
Window { id: win; visible: true; width: %(w)d; height: %(h)d; color: "BGCOLOR"
  Item { id: logic
    property var statusData: %(data)s
    property bool expanded: %(expanded)s
    property bool idleHidden: %(idle)s
    property bool inPanel: true
    property bool isRefreshing: %(refreshing)s
    property bool isLoading: false
    property string lastError: %(error)s
    property string lastUpdatedFormatted: "Atualizado às 10:00"
    property var updateInfo: NotchModel.updateSummary(statusData, I18n.tr)
    property color accentColor: "#3daee9"
    property var sessionOverlay: %(overlay)s
    property var calls: []
    function setPopupHovered(h) { calls.push("popupHover:" + h) }
    function closePopup() { calls.push("close") }
    function refreshCollector() { calls.push("refresh") }
    function loadStatus() { calls.push("load") }
  }
  FullRepresentation { id: f; plasmoidItem: logic; anchors.fill: parent }
  TestCase { id: tc; when: false; name: "t" }
  function all(it, out) { out = out || []; for (var i = 0; i < it.children.length; i++) { out.push(it.children[i]); all(it.children[i], out) } return out }
  function named(n) { return all(f).filter(function (k) { return k.objectName === n }) }
  function vis(n) { return named(n).filter(function (k) { return k.visible }) }
  function txt(n) { return vis(n).map(function (k) { return k.text }) }
  function buttons() { return all(f).filter(function (k) { return k.hint !== undefined && k.activeFocusOnTab === true && k.visible }) }
  function btn(text) { return buttons().filter(function (b) { return b.text === text || b.Accessible.name === text })[0] }
  function focusName() { var a = win.activeFocusItem; return a ? (a.text || a.objectName || "?") : null }
  property var result: ({})
  function done() {
    result.calls = logic.calls; result.cmds = Log.cmds; result.triggered = Plasmoid.triggered; result.nowMs = f.nowMs
    result.isOpen = f.isOpen; result.prefs = f.prefs
    result.size = [f.width, f.height]
    console.log("RESULT " + JSON.stringify(result)); Qt.quit() }
  Component.onCompleted: { var c = %(pcfg)s; for (var k in c) Plasmoid.configuration[k] = c[k]; Kirigami.Units.longDuration = %(dur)d; f.forceActiveFocus() }
  Timer { interval: %(delay)d; running: true; onTriggered: {
    var obs = function (k, v) { result[k] = v }
    var wait = function (ms) { tc.wait(ms) }
    %(drive)s
    if ("%(png)s") f.grabToImage(function (r) { r.saveToFile("%(png)s"); done() }); else done()
  } }
}
"""


def iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


def acct(provider, aid, label, active=False, native=None, weekly=None, health="valid", **extra):
    a = build_agent_account_status(provider=provider, account_id=aid, label=label, source="auto", health={"status": health},
                                   is_active=active, native_window=native, weekly_window=weekly,
                                   usage_details=extra.pop("usage_details", None), manual_invite_url=extra.pop("invite_url", None),
                                   manual_invite_count=extra.pop("invites", None))
    a.update(extra)
    return a


def hist():
    days = [{"date": f"2026-10-{d:02d}", "tokens": (d * 7919) % 90000} for d in range(1, 31)]
    return {"today": 12400, "week": 410000, "month": 1900000, "estimated": False, "daily_30d": days,
            "weekly_3m": [{"week_start": f"w{i}", "tokens": i * 200000} for i in range(1, 13)],
            "monthly_12m": [{"month": f"m{i}", "tokens": i * 900000} for i in range(1, 13)]}


def fixture():
    nat = lambda pct, level, h=1, m=20, fc=None: {"usage_percentage": pct, "release_time": iso(timedelta(hours=h, minutes=m, seconds=7)),
                                                  "window_seconds": 18000, "alert_level": level, "tokens_used": 120000, **({"forecast": fc} if fc else {})}
    wk = lambda pct, level: {"usage_percentage": pct, "cycle_reset_time": iso(timedelta(days=3, hours=5, minutes=30)),
                             "window_seconds": 604800, "alert_level": level}
    soon = {"exhausts_at": iso(timedelta(minutes=45)), "before_release": True}
    claude = [
        acct("claude", "work", "Trabalho", True, nat(82.0, "warning", fc=soon), wk(45.0, "normal"), token_history=hist(),
             usage_details={"tokens_by_model": [{"model": "opus", "tokens": 300000}], "current_model": "opus"},
             invites=2, invite_url="https://claude.ai/invite/abc", limit_changes=[{"window": "native", "kind": "duration"}]),
        acct("claude", "personal", "Pessoal", False, nat(12.0, "normal", 3, 5), None),
        acct("claude", "old", "Antiga", False, health="session_expired"),
    ]
    codex = [acct("codex", "cx", "Codex Pro", True, nat(95.0, "critical", 0, 25, {"exhausts_at": None}), wk(60.0, "normal"))]
    gemini = [acct("gemini", "g1", "Gemini velho", False, nat(30.0, "normal"), wk(20.0, "normal"), stale=True),
              acct("gemini", "g2", "Gemini vazio", False, no_data=True)]
    return {"agents": {"claude": {"name": "Claude", "accounts": claude}, "codex": {"name": "Codex", "accounts": codex},
                       "gemini": {"name": "Gemini", "accounts": gemini}},
            "updates": {"enabled": True, "items": {"widget": {"latest": "9.0.0", "available": True,
                        "url": "https://github.com/victorlcs87/plasma-ai-usage-widget/releases/tag/v9.0.0"}, "codex": {"latest": "2.0", "available": True}}}}


def popup(tmp_path, name, data=None, drive="", cfg=None, size=(460, 560), expanded=True, idle=False, refreshing=False, error="",
          overlay=None, reduced=False, delay=700):
    imp = tmp_path / "imp"
    for rel, (qmldir, files) in STUBS.items():
        d = imp / rel
        d.mkdir(parents=True)
        (d / "qmldir").write_text(qmldir)
        for f, body in files.items():
            (d / f).write_text(body)
    run = tmp_path / "run"
    run.mkdir()
    for f in FILES:
        shutil.copy(UI_DIR / f, run / f)
    png_dir = os.environ.get("AIU_PNG_DIR", "")
    (run / "h.qml").write_text((HARNESS % {
        "w": size[0], "h": size[1], "data": json.dumps(data if data is not None else fixture()), "expanded": str(expanded).lower(),
        "idle": str(idle).lower(), "refreshing": str(refreshing).lower(), "error": json.dumps(error), "overlay": json.dumps(overlay or {}),
        "pcfg": json.dumps(cfg or {}), "dur": 0 if reduced else 200, "delay": delay, "drive": drive,
        "png": f"{png_dir}/{name}.png" if png_dir else ""}).replace("BGCOLOR", os.environ.get("AIU_BG", "#303236")))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", "-I", str(imp), str(run / "h.qml")], env=env, capture_output=True, text=True, timeout=90)
    out = res.stdout + res.stderr
    line = next((l for l in out.splitlines() if "RESULT " in l), None)
    assert line, out
    bad = [l for l in res.stderr.splitlines() if "TypeError" in l or "ReferenceError" in l or "Unable to assign" in l]
    assert not bad, bad[:3]
    return json.loads(line.split("RESULT ", 1)[1])


def test_popup_renders_provider_blocks_and_cards(tmp_path):
    drive = """
    obs('providers', all(f).filter(function (k) { return k.objectName.indexOf('provider_') === 0 }).map(function (k) { return k.objectName }))
    obs('names', txt('accountName')); obs('pct', txt('pct')); obs('resets', txt('reset')); obs('words', txt('levelWord'))
    obs('forecast', txt('forecast')); obs('limit', txt('limitNote')); obs('session', txt('sessionWord'))
    """
    out = popup(tmp_path, "render", drive=drive, size=(460, 1400))
    assert out["providers"] == ["provider_claude", "provider_codex", "provider_gemini"]
    assert out["names"] == ["Trabalho", "Pessoal", "Antiga", "Codex Pro", "Gemini velho", "Gemini vazio"]
    assert "Warning" in out["words"] and "Critical" in out["words"]
    assert any("Runs out in" in t for t in out["forecast"]) and any("Limits changed" in t for t in out["limit"])
    # sem dado nunca é 0%: Antiga e Gemini vazio mostram "—"
    assert out["pct"].count("—") >= 3 and "0%" not in [p for p in out["pct"]]


def collector(cmds, args):
    """Comando do coletor (Collector.js) com este `args`; o caminho configurado (collectorPath) vazio vai como $1."""
    return any(c.startswith("bash -c 'c=") and c.endswith(" _ '' " + args) for c in cmds)


def test_popup_account_actions_call_the_same_commands(tmp_path):
    """Ações do popup: atualizar agora, configurar, ativar no sistema (shellQuote em tudo), copiar link, ver release."""
    data = fixture()
    data["agents"]["claude"]["accounts"][1]["id"] = "x'; touch /tmp/pwn; '"  # id hostil: tem de ir entre aspas
    drive = """
    btn("Update now").click(); btn("Settings").click()
    var sw = buttons().filter(function (b) { return b.text.indexOf("Activate on System") >= 0 })[0]
    obs('switchAccount', sw.visible); sw.click(); obs('busy', sw.enabled)
    btn("Copy Link").click()
    obs('release', btn("View release") !== undefined)
    """
    out = popup(tmp_path, "actions", data=data, drive=drive, size=(460, 1400))
    assert "refresh" in out["calls"] and out["triggered"] == ["configure"]
    assert out["switchAccount"] and out["busy"] is False
    evil = "'x'\\''; touch /tmp/pwn; '\\'''"
    assert collector(out["cmds"], f"'--switch-account' 'claude' {evil} '--status'")
    copy = next(c for c in out["cmds"] if "wl-copy" in c)
    assert copy.endswith(" _ 'https://claude.ai/invite/abc'") and "printf" in copy
    assert out["release"]


def test_switch_result_reloads_status_and_error_surfaces(tmp_path):
    drive = """
    var sw = buttons().filter(function (b) { return b.text.indexOf("Activate on System") >= 0 })[0]
    sw.click()
    for (var i = 0; i < Log.sources.length; i++) Log.sources[i].newData(Log.cmds[0], {"exit code": 1, stdout: "", stderr: "boom"})
    obs('err', logic.lastError)
    """
    out = popup(tmp_path, "switcherr", drive=drive, size=(460, 1400))
    assert out["err"] == "Error switching account: boom"


def test_account_management_actions_stay_in_config_with_quoted_args():
    """Criar, renomear, remover, capturar, login interativo, convites e órfãos seguem na configuração, via shellQuote."""
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    for flag in ("--add-account", "--capture-current", "--interactive-login", "--rename-account", "--remove-account",
                 "--reimport-orphan", "--delete-orphan"):
        assert f'shellQuote("{flag}")' in cfg or f"shellQuote(flag)" in cfg and flag in cfg, flag
    assert 'shellQuote("--remove-account")' in main and 'shellQuote("--refresh")' in main
    card = (UI_DIR / "AccountCard.qml").read_text(encoding="utf-8")
    assert 'shellQuote("--switch-account")' in card and "copyToClipboard" in card
    full = (UI_DIR / "FullRepresentation.qml").read_text(encoding="utf-8")
    assert 'internalAction("configure")' in full and "refreshCollector()" in full  # caminho para a gestão de contas


def test_countdown_ticks_each_second_only_while_popup_is_open(tmp_path):
    drive = """
    var a = txt('reset')[0]; var n0 = f.nowMs; wait(1300)
    obs('a', a); obs('b', txt('reset')[0]); obs('moved', f.nowMs - n0)
    logic.expanded = false; var n1 = f.nowMs; wait(1300); obs('frozen', f.nowMs === n1)
    logic.expanded = true; wait(1300); obs('resumed', f.nowMs > n1)
    logic.idleHidden = true; var n2 = f.nowMs; wait(1300); obs('idleFrozen', f.nowMs === n2); obs('idleOpen', f.isOpen)
    """
    out = popup(tmp_path, "tick", drive=drive)
    assert out["a"] != out["b"] and 1000 <= out["moved"] < 2500
    assert out["frozen"] and out["resumed"] and out["idleFrozen"] and out["idleOpen"] is False


def test_remaining_and_date_preferences_change_the_popup(tmp_path):
    drive = """
    obs('pct', txt('pct').slice(0, 2)); obs('reset', txt('reset')[0]); obs('rings', named('accountRing').map(function (r) { return [r.innerPct, r.outerPct] }).slice(0, 1))
    obs('marks', txt('levelMark').slice(0, 1))
    """
    base = popup(tmp_path / "a", "pref_used", drive=drive)
    rem = popup(tmp_path / "b", "pref_remaining", drive=drive, cfg={"usageDisplay": "remaining", "resetDisplay": "date"}, size=(460, 700))
    assert base["pct"] == ["82%", "45%"] and rem["pct"] == ["18%", "55%"]
    assert base["reset"].startswith("120.000 tokens • releases in ") and "releases in" not in rem["reset"] and " • releases " in rem["reset"]
    assert base["rings"] == [[82, 45]] and rem["rings"] == [[18, 55]]  # o arco mostra o que sobra
    assert base["marks"] == rem["marks"] == ["▲"]                  # o nível não muda com a preferência


def test_toggle_buttons_write_the_preference_and_reflect_the_current_one(tmp_path):
    drive = """
    btn("Remaining").click(); btn("Date").click(); wait(50)
    obs('pct', txt('pct')[0]); obs('checked', [btn("Remaining").checked, btn("Used").checked, btn("Date").checked, btn("Countdown").checked])
    obs('stored', [Plasmoid.configuration.usageDisplay, Plasmoid.configuration.resetDisplay])
    """
    out = popup(tmp_path, "toggle", drive=drive)
    assert out["pct"] == "18%" and out["checked"] == [True, False, True, False] and out["stored"] == ["remaining", "date"]


def test_invalid_config_falls_back_to_defaults(tmp_path):
    bad = {"usageDisplay": 5, "resetDisplay": "weird", "popupOpacity": "x", "popupProviderOrder": "zzz,codex", "popupHiddenProviders": 7}
    out = popup(tmp_path, "badcfg", cfg=bad, drive="obs('provs', all(f).filter(function (k) { return k.objectName.indexOf('provider_') === 0 }).map(function (k) { return k.objectName }))")
    assert out["prefs"]["remaining"] is False and out["prefs"]["date"] is False and out["prefs"]["opacity"] == 1
    assert out["provs"] == ["provider_codex", "provider_claude", "provider_gemini"]  # desconhecido sai, faltantes entram no fim
    low = popup(tmp_path / "x", "lowop", cfg={"popupOpacity": 10})
    assert low["prefs"]["opacity"] == 1
    assert popup(tmp_path / "y", "op85", cfg={"popupOpacity": 85})["prefs"]["opacity"] == 0.85
    assert popup(tmp_path / "z", "op60", cfg={"popupOpacity": 60})["prefs"]["opacity"] == 1  # valor antigo 50-79: padrão


def test_order_and_visibility_of_provider_cards(tmp_path):
    drive = "obs('provs', all(f).filter(function (k) { return k.objectName.indexOf('provider_') === 0 }).map(function (k) { return k.objectName })); obs('empty', txt('emptyMessage'))"
    out = popup(tmp_path, "order", cfg={"popupProviderOrder": "gemini,claude,codex", "popupHiddenProviders": "codex"}, drive=drive)
    assert out["provs"] == ["provider_gemini", "provider_claude"]
    none = popup(tmp_path / "n", "allhidden", cfg={"popupHiddenProviders": "claude,codex,gemini"}, drive=drive)
    assert none["provs"] == [] and "No provider visible" in none["empty"][0]
    empty = popup(tmp_path / "e", "noaccounts", data={"agents": {}}, drive=drive)
    assert "No accounts found" in empty["empty"][0]


def test_never_a_false_zero_and_no_active_account(tmp_path):
    drive = """
    obs('gem', all(f).filter(function (k) { return k.objectName === 'provider_gemini' })[0].children[0].Accessible.name)
    var rows = named('nativeRow'); obs('summ', rows.map(function (r) { return r.summary }))
    """
    out = popup(tmp_path, "zero", drive=drive, size=(460, 1400))
    assert any("no data" in s for s in out["summ"])
    stale = [s for s in out["summ"] if s.startswith("Daily Window: 30%")]
    assert stale and "normal" not in stale[0]  # obsoleto: sem nível, só o percentual esmaecido


def test_session_state_shows_word_for_the_active_account_only(tmp_path):
    drive = "obs('words', txt('sessionWord'))"
    cfg = {"sessionState": True}
    out = popup(tmp_path, "session", cfg=cfg, overlay={"claude/work": "busy", "claude/personal": "waiting", "codex/cx": "waiting"}, drive=drive)
    assert out["words"] == ["session busy", "waiting for you"]  # Claude/Trabalho e Codex; a Conta inativa não mostra
    assert popup(tmp_path / "o", "sessionoff", overlay={"claude/work": "busy"}, drive=drive)["words"] == []


def test_keyboard_focus_enter_and_escape(tmp_path):
    drive = """
    var all0 = buttons(); obs('count', all0.length)
    var seen = {}
    f.forceActiveFocus()
    for (var i = 0; i < all0.length + 6; i++) { tc.keyClick(Qt.Key_Tab); var a = win.activeFocusItem; if (a && a.hint !== undefined) seen[a.text || a.Accessible.name] = true }
    obs('reached', Object.keys(seen).length)
    var r = btn("Update now"); r.forceActiveFocus(); tc.keyClick(Qt.Key_Return); obs('enter', logic.calls.indexOf('refresh') >= 0)
    r.forceActiveFocus(); tc.keyClick(Qt.Key_Escape)
    """
    out = popup(tmp_path, "keys", drive=drive, size=(460, 1400))
    assert out["count"] >= 14 and out["reached"] >= out["count"] - 2  # tudo é alcançável por Tab (ocultos fora)
    assert out["enter"] and "close" in out["calls"]


def test_popup_texts_are_plain_text_and_hostile_values_stay_inert(tmp_path):
    data = fixture()
    data["agents"]["claude"]["accounts"][0]["name"] = "<b>x</b><img src=x>"
    data["agents"]["claude"]["accounts"][0]["fetch_error"] = {"message": "<i>falhou</i>"}
    drive = """
    var bad = all(f).filter(function (k) { return k.visible && typeof k.text === "string" && k.textFormat !== undefined && k.textFormat !== Text.PlainText && k.text !== "" })
    obs('bad', bad.map(function (k) { return k.text.slice(0, 30) }))
    """
    out = popup(tmp_path, "plain", data=data, drive=drive, size=(460, 1400), error="<b>erro</b>")
    assert out["bad"] == []


def test_reduced_motion_and_refreshing_state(tmp_path):
    drive = """
    obs('rot', f.spinning); obs('bar', named('refreshBar')[0].indeterminate)
    obs('label', txt('updatedLabel'))
    """
    run = popup(tmp_path / "a", "refreshing", drive=drive, refreshing=True)
    still = popup(tmp_path / "b", "refreshing_reduced", drive=drive, refreshing=True, reduced=True)
    assert run["rot"] is True and run["bar"] is True and run["label"] == ["Updating metrics..."]
    assert still["rot"] is False and still["bar"] is False and still["label"] == ["Updating metrics..."]


def test_idle_hidden_widget_does_not_animate_popup(tmp_path):
    out = popup(tmp_path, "idle", idle=True, drive="obs('anim', named('accountRing').map(function (r) { return r.shown }))", overlay={"claude/work": "busy"}, cfg={"sessionState": True})
    assert out["isOpen"] is False and not any(out["anim"])


def test_error_banner_and_background_opacity_render(tmp_path):
    out = popup(tmp_path, "error", error="Status cache not found. Run the collector.", cfg={"popupOpacity": 80}, drive="obs('bg', String(named('popupBackground')[0].color)); obs('err', named('errorBox')[0].visible)", size=(460, 300))
    assert out["err"] is True and out["bg"].startswith("#cc")  # alfa 0,8


def js(tmp_path, expr):
    """Executa JS puro dos módulos (ViewPrefs/NotchModel) no qml6."""
    for f in ("ViewPrefs.js", "NotchModel.js", "Presets.js", "PanelStyle.js", "I18n.js", "Collector.js"):
        (tmp_path / f).write_text((UI_DIR / f).read_text())
    (tmp_path / "t.qml").write_text('import QtQuick\nimport "ViewPrefs.js" as VP\nimport "NotchModel.js" as NM\nimport "I18n.js" as I18n\nimport "Collector.js" as CJ\nimport "Presets.js" as PR\nItem { Timer { interval: 50; running: true; onTriggered: { '
                                    'var tr = I18n.tr; '
                                    'console.log("RESULT " + JSON.stringify(EXPR)); Qt.quit() } } }'.replace("EXPR", expr))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", str(tmp_path / "t.qml")], env=env, capture_output=True, text=True, timeout=60)
    line = next(l for l in (res.stdout + res.stderr).splitlines() if "RESULT " in l)
    return json.loads(line.split("RESULT ", 1)[1])


def test_view_prefs_pure_functions(tmp_path):
    got = js(tmp_path, '[VP.shownPct(30, false), VP.shownPct(30, true), VP.shownPct(-1, true), VP.shownPct(0, true), VP.pctText(-1, true), VP.pctText(99.6, true),'
                       ' VP.countdown(9), VP.countdown(723), VP.countdown(7509), VP.countdown(300720), VP.countdown(-5),'
                       ' VP.config(null), VP.config({usageDisplay: "remaining", popupOpacity: 49}).opacity, VP.config({popupOpacity: 49.5}).opacity]')
    assert got[:11] == [30, 70, -1, 100, "\u2014", "0%", "9s", "12m 03s", "2h 05m 09s", "3d 11h 32m", "0s"]
    assert got[11] == {"remaining": False, "date": False, "opacity": 1, "order": ["claude", "codex", "gemini"]}
    assert got[12] == 1 and got[13] == 1  # fora da faixa 50..100: padrão, nunca clamp


def test_tooltip_and_description_follow_the_preferences(tmp_path):
    agents = {"claude": {"name": "Claude", "accounts": [acct("claude", "a", "A", True,
              {"usage_percentage": 40.0, "release_time": "2099-01-01T12:00:00+00:00", "window_seconds": 18000}, None)]}}
    expr = ('[NM.tooltipText(%(d)s, {}, tr, Date.parse("2098-12-31T12:00:00Z")), NM.tooltipText(%(d)s, {remaining: true, date: true}, tr, Date.parse("2098-12-31T12:00:00Z")),'
            ' NM.buildModel(%(d)s, {remaining: true}, tr, 0)[0].description]') % {"d": json.dumps({"agents": agents})}
    plain, pref, desc = js(tmp_path, expr)
    assert "Native window: 40% — releases in 1d 0h" in plain
    assert "Native window: 60% remaining — releases " in pref and "releases in" not in pref
    assert "Weekly: —" in pref and "Weekly: —" in plain  # sem dado: nunca 0%
    assert "Native window 60% remaining" in desc and "weekly -" in desc


def test_compact_panel_percent_follows_remaining_preference(tmp_path):
    from test_plasmoid_notch_render import render
    agents = {"claude": {"name": "Claude", "accounts": [acct("claude", "a", "A", True,
              {"usage_percentage": 40.0, "release_time": "2099-01-01T00:00:00+00:00", "window_seconds": 18000, "alert_level": "normal"},
              {"usage_percentage": 10.0, "cycle_reset_time": "2099-01-01T00:00:00+00:00", "window_seconds": 604800, "alert_level": "normal"})]}}
    base = render(tmp_path / "a", "rem_a", agents, panel={"panelStyle": "text", "panelMode": "pct"})
    rem = render(tmp_path / "b", "rem_b", agents, panel={"panelStyle": "text", "panelMode": "pct", "usageDisplay": "remaining"}, extra_cfg={"remaining": True})
    assert base["items"][0]["pct"] == "40%" and rem["items"][0]["pct"] == "60%"
    assert "60% remaining" in rem["model"][0]["description"]
    unknown = render(tmp_path / "c", "rem_c", {"claude": {"name": "Claude", "accounts": []}}, panel={"panelStyle": "text", "panelMode": "pct", "usageDisplay": "remaining"})
    assert unknown["items"][0]["pct"] == "\u2014"  # sem dado continua "—", nunca 100%


def test_popup_options_declared_with_safe_defaults_and_exposed():
    import xml.etree.ElementTree as ET
    root = ET.parse(UI_DIR.parent / "config" / "main.xml").getroot()
    entries = {e.attrib["name"]: e for e in root.iter() if e.tag.endswith("entry")}
    want = {"usageDisplay": ("String", "used"), "resetDisplay": ("String", "countdown"), "popupOpacity": ("Int", "100"),
            "popupProviderOrder": ("String", "claude,codex,gemini"), "popupHiddenProviders": ("String", None)}
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    for name, (typ, default) in want.items():
        assert entries[name].attrib["type"] == typ and (entries[name].find("{*}default").text or None) == default
        assert f"cfg_{name}" in cfg
    assert entries["popupOpacity"].find("{*}min").text == "80" and entries["popupOpacity"].find("{*}max").text == "100"
    assert "Accessible.name" in cfg.split('I18n.tr("Popup:")')[1][:5000]


def test_keyboard_focus_scrolls_the_list_to_the_focused_control(tmp_path):
    drive = """
    var last = buttons().filter(function (b) { return b.text.indexOf("Activate on System") >= 0 }).pop()
    var flick = named('popupFlick')[0]; obs('before', flick.contentY)
    last.forceActiveFocus(); wait(50)
    var y = last.mapToItem(flick, 0, 0).y; obs('inView', y >= 0 && y + last.height <= flick.height + 1); obs('after', flick.contentY)
    """
    out = popup(tmp_path, "scroll", drive=drive, size=(460, 400))
    assert out["before"] == 0 and out["after"] > 0 and out["inView"]


def lum(hexc):
    ch = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a, b):
    la, lb = lum(a) if isinstance(a, str) else a, lum(b) if isinstance(b, str) else b
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def blend(fg, bg, a):
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * a + y * (1 - a)):02x}" for x, y in zip(f, b))


def test_text_contrast_holds_at_the_opacity_floor_on_any_backdrop_and_when_dimmed():
    import re
    ui = dict(re.findall(r'(\w+): "(#[0-9a-f]{6})"', (UI_DIR / "Presets.js").read_text()))
    floor = float(re.search(r"OPACITY = \[(\d+),", (UI_DIR / "ViewPrefs.js").read_text()).group(1)) / 100
    for backdrop in ("#ffffff", "#000000", "#808080"):  # fundo claro, escuro e médio atrás do popup
        bg = blend(ui["panel"], backdrop, floor)
        assert contrast(ui["fg"], bg) >= 4.5 and contrast(ui["muted"], bg) >= 4.5, backdrop
    for a in (0.75,):  # linhas esmaecidas (obsoleto/sem dado) sobre o cartão
        assert contrast(blend(ui["muted"], ui["card"], a), ui["card"]) >= 4.5
        assert contrast(blend(ui["fg"], ui["card"], a), ui["card"]) >= 4.5
    row = (UI_DIR / "WindowRow.qml").read_text()
    assert "view.dim ? 0.75" in row


def test_repeated_buttons_have_unique_glyph_free_accessible_names(tmp_path):
    drive = "obs('names', buttons().map(function (b) { return b.Accessible.name }))"
    out = popup(tmp_path, "names", drive=drive, size=(460, 1400))
    names = out["names"]
    assert "Activate Pessoal on the system" in names and "Copy invite link for Trabalho" in names
    assert "History and details for Trabalho" in names and "30 days, Trabalho" in names
    assert len(names) == len(set(names))  # nenhum nome repetido
    assert not any(ch in n for n in names for ch in "⚡▾▸✓")


def test_tooltips_are_plain_text(tmp_path):
    for f in ("WindowRow.qml", "AccountCard.qml", "NotchButton.qml", "TokenHistory.qml"):
        assert "QQC2.ToolTip.text" not in (UI_DIR / f).read_text(), f  # a ToolTip padrão interpreta HTML
    tip = (UI_DIR / "PlainTip.qml").read_text()
    assert "textFormat: Text.PlainText" in tip and "tip.text" in tip
    data = fixture()
    data["agents"]["claude"]["accounts"][2]["health"]["message"] = "<img src=x onerror=alert(1)>"
    drive = """
    var tips = all(f).concat(all(f).reduce(function (a, k) { return a.concat(k.data || []) }, [])).filter(function (k) { return k.contentItem && k.contentItem.textFormat !== undefined })
    obs('n', tips.length); obs('bad', tips.filter(function (k) { return k.contentItem.textFormat !== Text.PlainText }).length)
    """
    out = popup(tmp_path, "tip", data=data, drive=drive, size=(460, 1400))
    assert out["n"] >= 5 and out["bad"] == 0


def test_token_summary_stays_visible_when_details_are_collapsed(tmp_path):
    drive = """
    var th = all(f).filter(function (k) { return k.summaryOnly !== undefined && k.history })
    obs('n', th.length); obs('summaryOnly', th.map(function (k) { return k.summaryOnly }))
    obs('chart', th.map(function (k) { return k.visible }))
    obs('labels', all(f).filter(function (k) { return k.visible && typeof k.text === 'string' && k.text.indexOf('Today ') === 0 }).length)
    var d = btn("History and details for Trabalho"); d.click(); wait(50)
    obs('after', th.map(function (k) { return k.summaryOnly }))
    """
    data = fixture()
    data["agents"]["claude"]["accounts"][1]["token_history"] = hist()  # inativa: recolhida
    out = popup(tmp_path, "summary", data=data, drive=drive, size=(460, 1400))
    assert out["n"] == 2 and out["summaryOnly"] == [False, True] and out["labels"] == 2  # resumo nas duas
    assert out["after"] == [True, True]


def test_empty_usage_details_do_not_offer_a_details_toggle(tmp_path):
    data = {"agents": {"claude": {"name": "Claude", "accounts": [acct("claude", "a", "A", True, usage_details={"tokens_by_model": [], "quota_by_model": []})]}}}
    out = popup(tmp_path, "nodetails", data=data, drive="obs('has', btn('History and details de A') !== undefined)")
    assert out["has"] is False


def test_hidden_providers_are_trimmed_and_empties_ignored():
    got = js(Path(__import__("tempfile").mkdtemp()), 'VP.config({popupHiddenProviders: " codex , ,gemini"}).order')
    assert got == ["claude"]


def test_page_keys_and_arrows_scroll_with_focus_on_root(tmp_path):
    drive = """
    var flick = named('popupFlick')[0]; f.forceActiveFocus()
    tc.keyClick(Qt.Key_PageDown); var a = flick.contentY; tc.keyClick(Qt.Key_Down); var b = flick.contentY
    tc.keyClick(Qt.Key_End); var e = flick.contentY; tc.keyClick(Qt.Key_Home)
    obs('k', [a, b, e, flick.contentY, flick.contentHeight - flick.height])
    """
    a, b, e, top, maxy = popup(tmp_path, "pagekeys", drive=drive, size=(460, 400))["k"]
    assert 0 < a < b and e == maxy and top == 0


def test_zero_remaining_keeps_a_level_marker_and_long_provider_names_elide(tmp_path):
    data = fixture()
    data["agents"]["codex"]["name"] = "Provedor com um nome absurdamente comprido para a largura do popup inteiro"
    data["agents"]["codex"]["accounts"][0]["native_window"]["usage_percentage"] = 100.0
    drive = """
    obs('texts', txt('levelMark')); obs('pcts', txt('pct').slice(0, 6))
    var h = all(f).filter(function (k) { return k.visible && k.elide === Text.ElideRight && typeof k.text === 'string' && k.text.indexOf('Provedor com') === 0 })[0]
    obs('elided', h ? h.truncated : null)
    """
    out = popup(tmp_path, "zero_remaining", data=data, cfg={"usageDisplay": "remaining"}, drive=drive, size=(460, 1400))
    assert "0%" in out["pcts"] and "\u25A0" in out["texts"] and out["elided"] is True  # 0% restante: forma e palavra do nível seguem


def test_provider_header_width_does_not_depend_on_its_own_block():
    """Causa do 'recursive rearrange' no Plasma real: Layout.maximumWidth ligado a block.width (do próprio layout)."""
    full = (UI_DIR / "FullRepresentation.qml").read_text(encoding="utf-8")
    assert "block.width" not in full and "flick.width * 0.5" in full


def test_collector_command_resolution_in_shell(tmp_path):
    """Collector.js executado de verdade no bash, com HOME falso: PATH, ~/.local/bin, pipx e collectorPath (último recurso)."""
    (tmp_path / "js").mkdir()

    def run(home, path_cfg, args="'--version'"):
        cmd = js(tmp_path / "js", f"CJ.buildCollectorCommand({json.dumps(args)}, {json.dumps(path_cfg)})")
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(UI_DIR.parent.parent.parent / "src")}
        return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env)

    def fake(path, tag):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\necho {tag} \"$@\"\n")
        path.chmod(0o755)

    home = tmp_path / "home"
    custom = home / "meu" / "ai-usage-collector"
    fake(custom, "custom")
    assert run(home, "~/meu/ai-usage-collector").stdout.strip() == "custom --version"          # ~ expandido, último recurso
    fake(home / ".local" / "bin" / "ai-usage-collector", "local")
    assert run(home, str(custom)).stdout.strip() == "local --version"                         # ~/.local/bin vem antes do configurado
    home2 = tmp_path / "home2"
    fake(home2 / ".local/share/pipx/venvs/plasma-ai-usage-collector/bin/ai-usage-collector", "pipx")
    assert run(home2, "").stdout.strip() == "pipx --version"
    res = run(tmp_path / "home3", "")                                                        # nada instalado: python3 -m
    assert res.returncode == 0 and res.stdout.startswith("ai-usage-collector ")
    res = run(tmp_path / "home3", "/nao/existe")                                             # configurado inexistente: não quebra
    assert res.returncode == 0
    # o caminho vai como argumento posicional: nunca interpretado pelo shell
    pwn = tmp_path / "pwn"
    assert run(tmp_path / "home3", f"x'; touch {pwn}; '").returncode == 0 and not pwn.exists()


def test_session_command_prefers_light_entrypoint_then_collector_then_configured_path(tmp_path):
    cmd = js(tmp_path, 'CJ.buildSessionCommand("/opt/x/ai-usage-collector")')
    order = ["command -v ai-usage-session-state", "ai-usage-collector --session-state", '"$c" --session-state', "python3 -m ai_usage_collector --session-state"]
    assert [cmd.index(o) for o in order] == sorted(cmd.index(o) for o in order)
    assert cmd.endswith(" _ '/opt/x/ai-usage-collector'") and "repositorios" not in cmd


def test_accent_has_at_least_3_to_1_on_the_pill_for_dark_system_accents_and_presets(tmp_path):
    from test_ui_contrast import ratio
    dark = ["#8e44ad", "#c0392b", "#1b5e20", "#1a237e", "#000000", "#3daee9"]
    got = js(tmp_path, "[" + ",".join(f'PR.onPill(%s, %s, %s, 3)' % tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)) for h in dark) + "]")
    for src, out in zip(dark, got):
        assert ratio(out, "#15171b") >= 3, (src, out)
    assert got[-1] == "#3daee9"  # já passa: não muda a cor padrão
    keep = js(tmp_path, '[PR.accents.map(function (a) { return a.color ? PR.onPill(parseInt(a.color.substr(1,2),16)/255, parseInt(a.color.substr(3,2),16)/255, parseInt(a.color.substr(5,2),16)/255, 3) : "" })]')[0]
    assert keep == [a if a else "" for a in [""] + ["#ff5fa2", "#ff5c5c", "#ff9f43", "#ffd84d", "#4cd964", "#2dd4bf", "#4da3ff", "#7b83ff", "#b57bff", "#f2f2f2", "#9aa0a6"]]  # predefinições intactas


def test_normal_level_text_has_4_5_to_1_on_the_card_even_with_a_dark_accent(tmp_path):
    from test_ui_contrast import ratio
    acc = ["#1d3557", "#8e44ad", "#1b5e20", "#000000", "#3daee9"]
    got = js(tmp_path, "[" + ",".join('PR.levelTextColor("normal", {r: %s, g: %s, b: %s})' % tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)) for h in acc) + "]")
    for src, out in zip(acc, got):
        assert ratio(out, "#1d2026") >= 4.5, (src, out)
    assert js(tmp_path, 'PR.levelTextColor("critical", {r: 0, g: 0, b: 0})') == "#ff4d4f"  # os outros níveis não mudam


def test_history_summary_keeps_all_three_metrics_with_a_large_font(tmp_path):
    """P2c: com fonte de 14 pt o resumo quebra em até 2 linhas em vez de cortar o "Mês" em silêncio."""
    drive = """
    Kirigami.Theme.smallFont = ({pointSize: 14}); wait(200)
    var l = named('historySummary').filter(function (k) { return k.visible })[0]
    obs('text', l.text); obs('trunc', l.truncated); obs('lines', l.lineCount)
    """
    out = popup(tmp_path, "histfont", drive=drive, size=(460, 900), cfg={})
    assert "Month" in out["text"] and out["trunc"] is False and out["lines"] <= 2
