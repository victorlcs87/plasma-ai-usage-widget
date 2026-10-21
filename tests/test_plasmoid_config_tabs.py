"""Configuração em abas (ticket 33 parte B): inventário, estado entre abas e comandos de aplicar.

Roda configGeneral.qml de verdade em qml6 offscreen; só o DataSource é stub (grava o comando, nunca executa).
"""
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui"
XML = UI_DIR.parent / "config" / "main.xml"
CFG = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
needs_qml = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")

TABS = ["tabGeral", "tabPainel", "tabPopup", "tabContas", "tabNotif"]
# Inventário: cada cfg_* pertence a exatamente uma aba
CFG_TAB = {
    "tabGeral": {"refreshIntervalClaude", "refreshIntervalCodex", "refreshIntervalGemini", "collectorPath"},
    "tabPainel": {"providerOrder", "hiddenProviders", "accentPreset", "panelStyle", "panelMode", "ringCenter", "metricSize", "panelMargin",
                 "floatingNotch", "floatEdge", "floatSize", "floatSnap", "floatScreen", "floatOffsetTop", "floatOffsetBottom", "floatOffsetLeft", "floatOffsetRight"},
    "tabPopup": {"hoverOpen", "usageDisplay", "resetDisplay", "popupOpacity", "popupProviderOrder", "popupHiddenProviders"},
    "tabContas": set(),
    "tabNotif": {"sessionState", "sessionAutoOpen", "sessionSound"},
}


def tab_blocks():
    """Texto de cada aba (do marcador `objectName: "tabX"` até o da seguinte)."""
    starts = [(t, CFG.index(f'objectName: "{t}"')) for t in TABS]
    out = {}
    for i, (t, s) in enumerate(starts):
        e = starts[i + 1][1] if i + 1 < len(starts) else CFG.index("    // Diálogo de confirmação de exclusão de Perfil Órfão")
        out[t] = CFG[s:e]
    return out


def test_inventory_cfg_properties_match_main_xml_and_each_has_one_tab():
    xml = {e.attrib["name"] for e in ET.parse(XML).getroot().iter() if e.tag.endswith("entry")}
    declared = set(re.findall(r"property \w+ cfg_(\w+)", CFG))
    # tudo do main.xml é editável aqui, exceto autoRefreshOnExpand (sem controle desde antes das abas)
    assert declared <= xml and xml - declared == {"autoRefreshOnExpand"}
    blocks = tab_blocks()
    for name in declared:
        helper = {"providerOrder": "moveProvider(", "hiddenProviders": "setProviderHidden(", "popupProviderOrder": "movePopupProvider(",
                  "popupHiddenProviders": "setPopupProviderHidden("}.get(name, "\0")
        where = [t for t, b in blocks.items() if re.search(rf"configRoot\.cfg_{name}\b|\"cfg_{name}\"", b) or helper in b]
        assert len(where) == 1, (name, where)  # nada some, nada duplica
        assert name in CFG_TAB[where[0]], (name, where)


def test_every_collector_command_is_still_quoted():
    for flag in ("--add-account", "--rename-account", "--remove-account", "--capture-current", "--interactive-login",
                 "--set-alert-config", "--set-notify-config", "--set-visibility-config", "--set-update-config"):
        assert f'shellQuote("{flag}")' in CFG, flag
    assert 'runOrphanAction("--reimport-orphan"' in CFG and 'runOrphanAction("--delete-orphan"' in CFG
    assert "shellQuote(flag)" in CFG
    # nenhum comando monta argumento sem shellQuote: todo `safeArgs +=`/`args +=` leva shellQuote
    for line in re.findall(r"^\s*(?:safeArgs|args) \+= .*$", CFG, re.M):
        assert "shellQuote(" in line, line


def test_qml_ids_are_unique_and_tabs_are_declared_in_order():
    ids = re.findall(r"^\s*id: (\w+)", CFG, re.M)
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    assert [CFG.index(f'objectName: "{t}"') for t in TABS] == sorted(CFG.index(f'objectName: "{t}"') for t in TABS)
    assert "StackLayout" in CFG and "currentIndex: 0" in CFG  # StackLayout mantém todas as abas vivas; Geral é a padrão


def test_every_control_of_old_layout_survives_in_a_tab():
    blocks = tab_blocks()
    expect = {"tabGeral": ["Refresh every (s):", "Alert by:", "Hide without the CLI running:", "Check for new versions once a day", "alertModeCombo"],
              "tabPainel": ["Accent color:", "Providers in the panel:", "Panel style:", "Ring center:", "Automatic margin"],
              "tabPopup": ["Open the popup on mouse hover", "Background opacity", "Providers in the popup:", "Release as countdown"],
              "tabContas": ["Add New Account", "captureCurrentAccountBtn", "interactiveLoginAccountBtn", "renameAccountBtn", "Orphan Profiles", "Re-import", "Delete"],
              "tabNotif": ["Show the session state (Claude and Codex)", "Play a sound at those moments", "--notify", "notifyDirty"]}
    for tab, needles in expect.items():
        for n in needles:
            assert n in blocks[tab] or (n.startswith("--") and "saveNotifySettings" in blocks[tab]), (tab, n)
    for dlg in ("orphanDeleteDialog", "confirmDialog", "renameDialog"):
        assert f"id: {dlg}" in CFG


STUB = ("module org.kde.plasma.plasma5support\nDataSource 1.0 DataSource.qml\nsingleton Log 1.0 Log.qml\n", {
    "Log.qml": "pragma Singleton\nimport QtQuick\nQtObject { property var cmds: [] }",
    "DataSource.qml": "import QtQuick\nQtObject { property string engine; property var connectedSources: []\n"
                      " signal newData(string s, var d); function connectSource(s) { Log.cmds.push(s) } function disconnectSource(s) {} }"})

HARNESS = """
import QtQuick
import QtQuick.Window
import QtTest
import org.kde.plasma.plasma5support
Window { id: win; visible: true; width: %(w)d; height: %(h)d; color: "#eff0f1"
  Rectangle { anchors.fill: parent; color: "#eff0f1" }
  ConfigGeneral { id: cfg; anchors.fill: parent }
  TestCase { id: tc; when: false; name: "t" }
  function all(it, out) { out = out || []; for (var i = 0; i < it.children.length; i++) { out.push(it.children[i]); all(it.children[i], out) } return out }
  function named(n) { return all(cfg).filter(function (k) { return k.objectName === n })[0] }
  function bytext(t) { return all(cfg).filter(function (k) { return k.text === t && k.visible })[0] }
  property var result: ({})
  function obs(k, v) { result[k] = v }
  function shot(names, i, done) {
    if (i >= names.length) { done(); return }
    named("configTabBar").currentIndex = i
    tc.wait(150)
    if (!names[i]) { shot(names, i + 1, done); return }
    win.contentItem.grabToImage(function (r) { r.saveToFile(names[i]); shot(names, i + 1, done) })
  }
  Component.onCompleted: { cfg.statusData = %(data)s }
  Timer { interval: 700; running: true; onTriggered: {
    %(drive)s
    var finish = function () { result.cmds = Log.cmds; console.log("RESULT " + JSON.stringify(result)); Qt.quit() }
    var pngs = %(pngs)s
    if (pngs.length) shot(pngs, 0, finish); else finish()
  } }
}
"""


def fixture():
    acc = lambda p, i, n, a: {"id": i, "provider": p, "name": n, "isActive": a, "health": {"status": "valid"},
                              "native_window": {"usage_percentage": 40.0}, "weekly_window": {"usage_percentage": 10.0}}
    return {"agents": {"claude": {"name": "Claude", "accounts": [acc("claude", "work", "Trabalho", True), acc("claude", "p2", "Pessoal", False)]},
                       "codex": {"name": "Codex", "accounts": [acc("codex", "cx", "Codex Pro", True)]},
                       "gemini": {"name": "Gemini", "accounts": []}},
            "orphan_profiles": [{"provider": "claude", "id": "orf1", "email": "x@y.z"}],
            "alerts": {"mode": "pace", "warning": 70, "critical": 90},
            "notifications": {"warning": 80, "critical": 95, "early": True, "reset": False, "muted": []},
            "visibility": {"hide_when_not_running": "off"}, "updates": {"enabled": True}}


def config(tmp_path, drive="", size=(560, 640), pngs=None):
    imp = tmp_path / "imp" / "org/kde/plasma/plasma5support"
    imp.mkdir(parents=True)
    (imp / "qmldir").write_text(STUB[0])
    for f, body in STUB[1].items():
        (imp / f).write_text(body)
    run = tmp_path / "run"
    run.mkdir()
    for f in ("Presets.js", "I18n.js", "Collector.js", "PanelStyle.js", "ViewPrefs.js", "FloatingGeometry.js"):
        shutil.copy(UI_DIR / f, run / f)
    shutil.copy(UI_DIR / "configGeneral.qml", run / "ConfigGeneral.qml")
    shutil.copy(UI_DIR / "WrapCheckBox.qml", run / "WrapCheckBox.qml")
    (run / "h.qml").write_text(HARNESS % {"w": size[0], "h": size[1], "data": json.dumps(fixture()), "drive": drive, "pngs": json.dumps(pngs or [])})
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
    res = subprocess.run(["qml6", "-I", str(tmp_path / "imp"), str(run / "h.qml")], env=env, capture_output=True, text=True, timeout=90)
    out = res.stdout + res.stderr
    line = next((l for l in out.splitlines() if "RESULT " in l), None)
    assert line, out
    bad = [l for l in res.stderr.splitlines() if "TypeError" in l or "ReferenceError" in l or "Unable to assign" in l]
    assert not bad, bad[:3]
    return json.loads(line.split("RESULT ", 1)[1])


@needs_qml
def test_each_tab_renders_without_errors_and_geral_is_the_default(tmp_path):
    png_dir = os.environ.get("AIU_PNG_DIR", "")
    pngs = [f"{png_dir}/tab_{t}.png" if png_dir else "" for t in TABS]
    drive = """
    var bar = named("configTabBar"); obs('current', bar.currentIndex); obs('count', bar.count)
    obs('names', all(bar).filter(function (k) { return k.Accessible.role === Accessible.PageTab }).map(function (k) { return k.Accessible.name }))
    obs('stack', named("tabGeral").visible)
    """
    out = config(tmp_path, drive=drive, pngs=pngs)
    assert out["current"] == 0 and out["count"] == 5 and out["stack"] is True
    assert out["names"] == ["General", "Panel", "Popup", "Accounts", "Notifications"]


@needs_qml
def test_edited_unapplied_values_survive_tab_switches(tmp_path):
    drive = """
    var bar = named("configTabBar")
    bar.currentIndex = 2; tc.wait(100)
    var sp = all(cfg).filter(function (k) { return k.from === 80 && k.to === 100 })[0]; sp.value = 95
    cfg.alertMode = "threshold"; cfg.alertsDirty = true
    for (var i = 0; i < 5; i++) { bar.currentIndex = i; tc.wait(60) }
    bar.currentIndex = 2; tc.wait(60)
    obs('opacity', sp.value); obs('alert', [cfg.alertMode, cfg.alertsDirty]); obs('alive', all(cfg).filter(function (k) { return k.from === 80 && k.to === 100 }).length)
    cfg.cfg_panelStyle = "bar"; bar.currentIndex = 1; tc.wait(60); obs('style', cfg.cfg_panelStyle)
    """
    out = config(tmp_path, drive=drive)
    assert out["opacity"] == 95 and out["alert"] == ["threshold", True] and out["alive"] == 1 and out["style"] == "bar"


@needs_qml
def test_apply_and_account_actions_call_the_same_commands(tmp_path):
    drive = """
    cfg.saveAlertSettings(); cfg.saveHideSettings(); cfg.saveNotifySettings(); cfg.saveUpdateSetting(true)
    var orf = cfg.statusData.orphan_profiles[0]
    cfg.runOrphanAction("--reimport-orphan", orf, false); cfg.runOrphanAction("--delete-orphan", orf, true)
    var acc = cfg.statusData.agents.claude.accounts[1]
    cfg.requestRenameAccount(acc); cfg.confirmRename()
    cfg.requestDeleteAccount(acc); cfg.confirmDelete()
    """
    cmds = config(tmp_path, drive=drive)["cmds"]
    joined = "\n".join(cmds)
    for needle in ("'--set-alert-config' '--alert-mode' 'pace' '--alert-warning' '70' '--alert-critical' '90'",
                   "'--set-visibility-config' '--hide-when-not-running' 'off'", "'--set-notify-config'",
                   "'--set-update-config' '--update-check' 'on'", "'--reimport-orphan' 'claude' 'orf1'",
                   "'--delete-orphan' 'claude' 'orf1' '--confirm'", "'--rename-account' 'claude' 'p2'", "'--remove-account' 'claude' 'p2'"):
        assert needle in joined, needle
    assert all(c.startswith("bash -c 'c=${1/#\\~/$HOME}; shift; if command -v ai-usage-collector") for c in cmds if not c.startswith("cat "))  # cat = leitura do status (stub, não executa)


@needs_qml
def test_narrow_width_still_renders_every_tab(tmp_path):
    png_dir = os.environ.get("AIU_PNG_DIR", "")
    pngs = [f"{png_dir}/narrow_{t}.png" if png_dir else "" for t in TABS]
    config(tmp_path, size=(360, 560), pngs=pngs)


def test_header_is_generic_and_add_account_header_is_keyboard_reachable():
    assert 'I18n.tr("Configuration")' in CFG and "AI Account Management" not in CFG
    blocks = tab_blocks()
    assert "manage their lifecycle" in blocks["tabContas"] and "manage their lifecycle" not in CFG.split('objectName: "tabGeral"')[0]
    assert "MouseArea" not in CFG  # nenhum controle só por mouse: o botão Expandir/Recolher é focável
    assert 'Accessible.name: I18n.tr("Add New Account")' in blocks["tabContas"]


@needs_qml
def test_tabs_scroll_with_visible_arrows_in_a_narrow_window(tmp_path, monkeypatch):
    """R2 P2-4: em janela estreita as abas não ficam cortadas sem aviso: aparecem as setas e a aba atual rola para a vista."""
    monkeypatch.setenv("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")  # o estilo Basic reparte a largura e nunca transborda
    drive = """
    var bar = named("configTabBar"), c = bar.contentItem
    obs('arrows', [named("tabsScrollLeft").visible, named("tabsScrollRight").visible])
    bar.currentIndex = 4; tc.wait(300); obs('moved', c.contentX > 0)
    """
    out = config(tmp_path, drive=drive, size=(330, 640))
    assert out["arrows"] == [True, True] and out["moved"] is True
    (tmp_path / "w").mkdir()
    wide = config(tmp_path / "w", drive=drive, size=(900, 640))
    assert wide["arrows"] == [False, False]  # cabendo, sem setas
