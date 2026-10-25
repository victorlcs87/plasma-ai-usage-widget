"""Ticket 77: botão de atualizar o widget no popup (estado no main.qml, componente WidgetUpdate.qml), qml6 offscreen.

Nenhum comando roda: o plasmoidItem é falso e só registra as chamadas. O estado real (DataSources) é conferido no main.qml.
"""
import json
import re
import shutil
from pathlib import Path

import pytest
from test_plasmoid_popup import popup, js, fixture, UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")


def wu(tmp_path, drive, with_update=True, **kw):
    data = fixture()
    if not with_update:
        data.pop("updates")
    pre = "var set = function (s) { logic.widgetUpdate = Object.assign({state: 'idle', result: '', version: '', step: ''}, s); wait(60) }\n"
    out = popup(tmp_path, "wu", data=data, drive=pre + drive, size=(460, 900), **kw)
    out["calls"] = [c for c in out["calls"] if not c.startswith("popupHover")]  # ruído de hover do popup
    return out


BTNS = "obs('btns', buttons().map(function (b) { return b.text }))"


def test_without_new_version_offers_to_check_and_nothing_runs_on_open(tmp_path):
    out = wu(tmp_path, "wait(500); " + BTNS, with_update=False)
    assert "Check for updates" in out["btns"] and not any(b.startswith("Update to") for b in out["btns"])
    assert out["calls"] == [] and out["cmds"] == []  # abrir o popup não busca nem atualiza


def test_with_new_version_offers_update_to_it(tmp_path):
    out = wu(tmp_path, BTNS)
    assert "Update to v9.0.0" in out["btns"] and "Check for updates" not in out["btns"]


def test_check_click_calls_check_only(tmp_path):
    out = wu(tmp_path, "btn('Check for updates').click(); wait(50)", with_update=False)
    assert out["calls"] == ["check"]


@pytest.mark.parametrize("result,text", [
    ("atual", "You already have the latest version."),
    ("indisponivel", "Could not check for updates right now. Try again later."),
    ("desligada", "Update checks are turned off in the settings."),
])
def test_check_results_without_new_version(tmp_path, result, text):
    out = wu(tmp_path, "set({result: '%s'}); obs('note', txt('widgetUpdateNote')); %s" % (result, BTNS), with_update=False)
    assert out["note"] == [text] and "Check for updates" in out["btns"]


def test_atual_result_hides_a_stale_status_json_update(tmp_path):
    out = wu(tmp_path, "set({result: 'atual', version: '1.2.0'}); " + BTNS)
    assert "Check for updates" in out["btns"] and "Update to v9.0.0" not in out["btns"]


def test_found_result_offers_update_with_the_found_version(tmp_path):
    out = wu(tmp_path, "set({result: 'nova', version: '1.3.0'}); " + BTNS, with_update=False)
    assert "Update to v1.3.0" in out["btns"]


def test_cooldown_disables_check_but_not_a_found_update(tmp_path):
    out = wu(tmp_path, """
    logic.widgetCheckCooldown = true; wait(50); obs('dis', btn('Check for updates').enabled); btn('Check for updates').click(); wait(50)
    set({result: 'nova', version: '1.3.0'}); obs('upd', btn('Update to v1.3.0').enabled)
    """, with_update=False)
    assert out["dis"] is False and out["calls"] == [] and out["upd"] is True


def test_click_opens_inline_confirmation_with_versions_origin_and_no_sudo(tmp_path):
    out = wu(tmp_path, """
    btn('Update to v9.0.0').click(); wait(50)
    obs('conf', vis('widgetUpdateConfirm').length); obs('title', txt('widgetUpdateConfirmTitle')); obs('det', txt('widgetUpdateConfirmDetails'))
    obs('focus', focusName()); obs('dis', btn('Update to v9.0.0').enabled)
    """)
    assert out["conf"] == 1 and out["title"] == ["Update the widget from v1.2.0 to v9.0.0?"] and out["calls"] == ["ask"]
    assert "GitHub Releases" in out["det"][0] and "No sudo" in out["det"][0] and out["focus"] == "Cancel"
    assert out["dis"] is False  # com a pergunta aberta o botão principal fica desligado


def test_cancel_and_escape_have_no_effect(tmp_path):
    out = wu(tmp_path, """
    btn('Update to v9.0.0').click(); wait(50); btn('Cancel').click(); wait(50)
    obs('c1', vis('widgetUpdateConfirm').length); obs('back', btn('Update to v9.0.0') !== undefined)
    btn('Update to v9.0.0').click(); wait(50); tc.keyClick(Qt.Key_Escape); wait(50); obs('c2', vis('widgetUpdateConfirm').length)
    btn('Update to v9.0.0').click(); wait(50); f.forceActiveFocus(); tc.keyClick(Qt.Key_Escape); wait(50); obs('c3', vis('widgetUpdateConfirm').length)
    """)
    assert out["c1"] == 0 and out["back"] and out["c2"] == 0 and out["c3"] == 0
    assert "update" not in out["calls"] and "close" not in out["calls"] and out["cmds"] == []


def test_confirm_runs_update_and_enter_on_cancel_does_not(tmp_path):
    out = wu(tmp_path, """
    btn('Update to v9.0.0').click(); wait(50); tc.keyClick(Qt.Key_Return); wait(50)  // foco inicial no Cancel
    obs('afterCancelEnter', logic.calls.indexOf('update') >= 0)
    btn('Update to v9.0.0').click(); wait(50); btn('Update').click(); wait(50)
    """)
    assert out["afterCancelEnter"] is False and out["calls"].count("update") == 1


def test_confirmation_closes_with_the_popup(tmp_path):
    out = wu(tmp_path, "btn('Update to v9.0.0').click(); wait(50); logic.expanded = false; wait(80); obs('state', logic.widgetUpdate.state)")
    assert out["state"] == "idle" and "cancel" in out["calls"]


def test_updating_disables_button_and_shows_step_name(tmp_path):
    out = wu(tmp_path, """
    set({state: 'atualizando', step: 'plasmoid_download', to: '9.0.0'})
    var b = btn('Updating the widget…'); obs('dis', b.enabled); b.click(); wait(50)
    obs('bar', vis('widgetUpdateBar').length); obs('step', txt('widgetUpdateStep')); obs('conf', vis('widgetUpdateConfirm').length)
    set({state: 'atualizando', step: 'plasmoid_install', to: '9.0.0'}); obs('step2', txt('widgetUpdateStep'))
    """)
    assert out["dis"] is False and out["calls"] == [] and out["bar"] == 1 and out["conf"] == 0
    assert out["step"] == ["Downloading the widget"] and out["step2"] == ["Installing the widget"]


CAUSES = {
    "python_indisponivel": "Python 3 with venv support is not available. Install it and try again.",
    "rede": "Could not download the update. Check your internet connection and try again.",
    "versao_inexistente": "This version is not available yet. Try again later.",
    "permissao": "Permission denied while writing to the installation folders.",
    "conflito_em_local_bin": "Another file already exists in ~/.local/bin and was not overwritten.",
    "verificacao": "The download did not pass the integrity check. Nothing was changed.",
    "sem_hash": "This collector cannot verify the widget download, so the update was not applied. Update manually from the release page.",
    "kpackagetool": "kpackagetool6 could not install the widget package. The collector was updated; update the widget manually from the release page.",
    "falha": "The update failed.",
}


@pytest.mark.parametrize("cause", CAUSES)
def test_error_shows_classified_cause_as_plain_text_and_try_again(tmp_path, cause):
    out = wu(tmp_path, """
    set({state: 'erro', cause: '%s', message: '<b>x</b> boom', failedStep: 'plasmoid_verify'})
    obs('cause', txt('widgetUpdateCause')); obs('msg', txt('widgetUpdateMessage')); obs('fmt', named('widgetUpdateMessage')[0].textFormat === Text.PlainText)
    btn('Try again').click(); wait(50); obs('conf', vis('widgetUpdateConfirm').length)
    """ % cause)
    assert out["cause"] == ["⚠ " + CAUSES[cause]]
    assert out["msg"] == ["Details: <b>x</b> boom\nStopped during: Verifying the widget download"] and out["fmt"]
    assert out["conf"] == 1 and "update" not in out["calls"]  # tentar de novo também pede confirmação


def test_verification_says_nothing_changed_and_sem_hash_points_to_manual_update():
    assert "Nothing was changed" in CAUSES["verificacao"] and "manually" in CAUSES["sem_hash"]


def test_done_asks_before_reloading_and_never_reloads_by_itself(tmp_path):
    out = wu(tmp_path, """
    set({state: 'concluido', to: '9.0.0'})
    obs('done', txt('widgetUpdateDoneText')); obs('btns', buttons().map(function (b) { return b.text })); obs('conf0', vis('widgetReloadConfirm').length)
    wait(300); obs('calls0', logic.calls.filter(function (c) { return c.indexOf('popupHover') < 0 }))
    btn('Reload the widget').click(); wait(50)
    obs('conf1', vis('widgetReloadConfirm').length); obs('det', txt('widgetReloadDetails')); obs('focus', focusName())
    btn('Not now').click(); wait(50); obs('conf2', vis('widgetReloadConfirm').length)
    btn('Reload the widget').click(); wait(50); tc.keyClick(Qt.Key_Escape); wait(50); obs('conf3', vis('widgetReloadConfirm').length)
    btn('Reload the widget').click(); wait(50); btn('Reload now').click(); wait(50)
    """)
    assert out["done"] == ["✓ Updated to v9.0.0. Reload the widget to start using it."] and out["conf0"] == 0
    assert "Check for updates" not in out["btns"] and out["calls0"] == []
    assert out["conf1"] == 1 and "Plasma shell" in out["det"][0] and out["focus"] == "Not now"
    assert out["conf2"] == 0 and out["conf3"] == 0 and out["calls"] == ["reload"] and "close" not in out["calls"]


def test_main_state_wiring_is_click_only_and_guarded():
    main = (UI_DIR / "main.qml").read_text()
    for fn in ("checkWidgetUpdate", "askWidgetUpdate", "startWidgetUpdate", "reloadWidget"):
        assert main.count("root.%s(" % fn) == 0 and main.count("function %s(" % fn) == 1  # sem gatilho próprio (partida/timer/popup)
    for name in ("widgetCheckSource", "widgetUpdateSource", "widgetReloadSource"):
        assert main.count(name + ".connectSource") == 1
    start = main.split("function startWidgetUpdate()")[1].split("function reloadWidget")[0]
    assert 'state !== "confirmando" ||' in start and "Collector.buildUpdateCommand(script, root.widgetUpdateVersion)" in start
    ask = main.split("function askWidgetUpdate()")[1].split("function cancelWidgetUpdate")[0]
    assert "widgetUpdateBusy" in ask and 'collectorInstall.state === "running"' in ask
    assert 'state === "concluido"' in main.split("function reloadWidget()")[1].split("}")[0]
    assert "interval: 5000" in main.split("id: widgetCooldown")[1].split("}")[0]
    assert "widgetCooldown.restart()" in main.split("id: widgetCheckSource")[1].split("id: widgetCooldown")[0]


def test_component_is_reusable_and_accessible():
    comp = (UI_DIR / "WidgetUpdate.qml").read_text()
    assert "property var plasmoidItem" in comp and "Accessible.role: Accessible.AlertMessage" in comp
    assert "Keys.onEscapePressed" in comp and comp.count("textFormat: Text.PlainText") >= 8
    full = (UI_DIR / "FullRepresentation.qml").read_text()
    assert "WidgetUpdate {" in full and "plasmoidItem: fullRoot.plasmoidItem" in full


def test_js_check_update_parser(tmp_path):
    out = js(tmp_path, """({
      nova: CJ.parseCheckUpdate('{"update":"nova","version":"1.3.0","url":"https://x"}'), v: CJ.parseCheckUpdate('{"update":"nova","version":"v1.3.0"}'),
      atual: CJ.parseCheckUpdate('{"update":"atual","version":"1.2.0"}\\n'), off: CJ.parseCheckUpdate('{"update":"desligada"}'),
      ind: CJ.parseCheckUpdate('{"update":"indisponivel"}'),
      bad: ["", "nao json", "[]", "null", '{"update":"nova"}', '{"update":"nova","version":"1.3.0;rm -rf ~"}', '{"update":"hack"}', null].map(function (s) { return CJ.parseCheckUpdate(s) })})""")
    assert out["nova"] == {"update": "nova", "version": "1.3.0"} and out["v"]["version"] == "1.3.0"
    assert out["atual"] == {"update": "atual", "version": "1.2.0"} and out["off"]["update"] == "desligada" and out["ind"]["update"] == "indisponivel"
    assert out["bad"] == [{"update": "indisponivel", "version": ""}] * 8


def test_js_update_command_is_strict_and_parser_knows_the_new_steps_and_causes(tmp_path):
    lines = '{"step":"plasmoid_download","status":"start","message":""}\n'
    out = js(tmp_path, """({
      ok: CJ.buildUpdateCommand("/home/a b/x.py", "1.3.0"),
      bad: ["", "1.3", "1.3.0;id", "$(id)", "v1.3.0", null].map(function (v) { return CJ.buildUpdateCommand("/s.py", v) }),
      cur: CJ.currentStep(%(l)s), hash: CJ.parseUpdate('{"result":"error","cause":"sem_hash","message":"m","log":[]}', 1).cause,
      kpkg: CJ.parseUpdate('{"step":"plasmoid_install","status":"error","message":""}\\n{"result":"error","cause":"kpackagetool","message":"m","log":[]}', 1),
      ok2: CJ.parseUpdate('{"result":"ok","cause":null,"message":"","log":[]}', 0).ok})""" % {"l": json.dumps(lines)})
    assert out["ok"] == "python3 '/home/a b/x.py' update --version '1.3.0'" and out["bad"] == [""] * 6
    assert out["cur"] == "plasmoid_download" and out["hash"] == "sem_hash" and out["ok2"] is True
    assert out["kpkg"]["cause"] == "kpackagetool" and out["kpkg"]["failedStep"] == "plasmoid_install"


def test_pt_br_translates_the_new_strings():
    po = (Path(__file__).resolve().parent.parent / "po" / "pt_BR.po").read_text()
    for msg in ("Check for updates", "Update to v%1", "Reload the widget", "Reload now", "Not now",
                "Update the widget from v%1 to v%2?", "The update failed.", "Downloading the widget"):
        m = re.search(r'msgid "%s"\nmsgstr "(.+)"' % re.escape(msg), po)
        assert m and m.group(1) != msg, msg


def test_js_state_machine_partial_complete_missing_exit_code_and_error_cause(tmp_path):
    step = json.dumps('{"step":"plasmoid_download","status":"start","message":""}\n')
    okl = json.dumps('{"result":"ok","cause":null,"message":"","log":[]}')
    errl = json.dumps('{"result":"error","cause":"rede","message":"%s","log":["l1"]}' % ("m" * 600))
    out = js(tmp_path, """(function () {
      var cur = {state: 'atualizando', result: 'nova', version: '9.0.0', step: '', to: '9.0.0'};
      return {
        partial: CJ.widgetUpdateOnData(cur, %(step)s, undefined),
        ok: CJ.widgetUpdateOnData(cur, %(ok)s, 0),
        okNoLine: CJ.widgetUpdateOnData(cur, '', 0),
        err: CJ.widgetUpdateOnData(cur, %(err)s, 1),
        stuck: [CJ.widgetUpdateStuck(cur), CJ.widgetUpdateStuck({state: 'buscando', result: ''}), CJ.widgetUpdateStuck({state: 'idle'}),
                CJ.widgetUpdateStuck({state: 'concluido'}), CJ.widgetUpdateStuck({state: 'erro'})]}})()""" % {"step": step, "ok": okl, "err": errl})
    assert out["partial"] == {"done": False, "next": {"state": "atualizando", "result": "nova", "version": "9.0.0", "step": "plasmoid_download", "to": "9.0.0"}}
    assert out["ok"]["done"] and out["ok"]["next"]["state"] == "concluido" and out["ok"]["next"]["to"] == "9.0.0"  # ok -> concluido, to preservado
    assert out["okNoLine"]["next"]["state"] == "erro" and out["okNoLine"]["next"]["cause"] == "falha"  # exit 0 sem linha de resultado não é sucesso
    e = out["err"]["next"]
    assert out["err"]["done"] and e["state"] == "erro" and e["cause"] == "rede" and e["log"] == ["l1"] and len(e["message"]) == 500
    s0, s1, *rest = out["stuck"]
    assert s0["state"] == "erro" and s0["cause"] == "falha" and s1["cause"] == "falha" and rest == [None] * 3


def test_js_message_is_capped_for_install_and_update(tmp_path):
    out = js(tmp_path, """({i: CJ.parseInstall('{"result":"ok","message":"%s"}', 0).message.length, u: CJ.parseUpdate('{"result":"error","cause":"x","message":"%s"}', 1).message.length})""" % ("a" * 900, "a" * 900))
    assert out == {"i": 500, "u": 500}


def test_main_guards_both_sides_watchdog_and_reload_disconnect():
    main = (UI_DIR / "main.qml").read_text()
    assert 'widgetUpdateBusy) return' in main.split("function installCollector()")[1].split("var script")[0]
    assert 'collectorInstall.state === "running"' in main.split("function startWidgetUpdate()")[1].split("var script")[0]
    assert '"concluido") return' in main.split("function checkWidgetUpdate()")[1].split("setWidgetUpdate")[0]
    assert "dismissWidgetUpdate" not in main
    assert "disconnectSource(sourceName)" in main.split("id: widgetReloadSource")[1].split("}")[0]
    dog = main.split("Watchdog")[1].split("Plasma5Support")[0]
    assert "30000" in dog and "600000" in dog and "running: root.widgetUpdateBusy" in dog and "widgetUpdateStuck" in dog
    assert main.count("connectedSources = []") >= 2
