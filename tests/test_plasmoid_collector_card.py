"""Ticket 49: card do Coletor no popup e marcador no painel, por estado do `status` (harness qml6, sem executar nada)."""
import json
import shutil

import pytest
from test_plasmoid_notch_render import acct, render
from test_plasmoid_popup import popup, js, UI_DIR
from test_ui_contrast import ratio, _ui

pytestmark = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")

DRIVE = """
logic.collectorStatus = Collector.parseStatus(%s, %d); wait(100)
obs('card', vis('collectorCard').length); obs('title', txt('collectorTitle')); obs('body', txt('collectorBody'))
obs('msg', txt('collectorMessage')); obs('actions', vis('collectorActions').length); obs('buttons', buttons().map(function (b) { return b.text }))
var c = named('collectorCard')[0]; obs('y', c.mapToItem(f, 0, 0).y); obs('blockY', named('provider_claude')[0].mapToItem(f, 0, 0).y)
"""


def card(tmp_path, payload, code=0, **kw):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return popup(tmp_path, "card", drive=DRIVE % (json.dumps(raw), code), size=(460, 900), **kw)


def st(state, **kw):
    return {"state": state, "installed": None, "required": "1.2.0", "path": None, "message": "", **kw}


def test_ausente_card_sits_above_accounts_with_reserved_action_row_but_no_button(tmp_path):
    out = card(tmp_path, st("ausente", message="Coletor não encontrado."))
    assert out["card"] == 1 and out["title"] == ["⚠ Collector not installed"]
    assert "needs the collector" in out["body"][0] and out["msg"] == ["Details: Coletor não encontrado."]
    assert out["actions"] == 1 and "Install collector" in out["buttons"]  # ticket 50: botão na linha de ações
    assert 0 <= out["y"] < out["blockY"]


def test_desatualizado_shows_both_versions(tmp_path):
    out = card(tmp_path, st("desatualizado", installed="1.0.0"))
    assert out["title"] == ["⚠ Collector is older than the widget: 1.0.0 installed, 1.2.0 required"] and out["actions"] == 1
    assert "Update collector" in out["buttons"] and "Install collector" not in out["buttons"]


def test_python_indisponivel_says_what_to_install_without_actions(tmp_path):
    out = card(tmp_path, st("python_indisponivel"))
    assert out["title"] == ["⚠ Python 3 is not available"] and "sudo apt install python3-venv" in out["body"][0]
    assert "sudo pacman -S python" in out["body"][0] and out["actions"] == 0


def test_mais_novo_is_informative_only_and_ok_shows_nothing(tmp_path):
    out = card(tmp_path, st("mais_novo", installed="2.0.0"))
    assert out["card"] == 1 and "newer than the widget: 2.0.0 installed, 1.2.0 required" in out["title"][0]
    assert out["actions"] == 0 and not any("owngrade" in b or "nstall" in b for b in out["buttons"])
    assert card(tmp_path / "ok", st("ok", installed="1.2.0"))["card"] == 0


@pytest.mark.parametrize("raw,code", [("", 1), ("not json", 0), ("[]", 0), ('{"state":"hack"}', 0), ("null", 0)])
def test_invalid_status_output_means_unknown_state_and_no_card(tmp_path, raw, code):
    assert card(tmp_path, raw, code)["card"] == 0


def test_missing_python3_exit_127_is_python_unavailable(tmp_path):
    assert card(tmp_path, "", 127)["title"] == ["⚠ Python 3 is not available"]


def test_hostile_message_is_plain_text(tmp_path):
    out = card(tmp_path, st("ausente", message="<b>x</b><img src=x>"))
    assert out["msg"] == ["Details: <b>x</b><img src=x>"]
    assert "textFormat: Text.PlainText" in (UI_DIR / "FullRepresentation.qml").read_text().split('objectName: "collectorMessage"')[1][:500]


def test_panel_marker_has_name_and_dark_backdrop_only_when_attention(tmp_path):
    ag = {"claude": {"name": "Claude", "accounts": [acct(True)]}}
    out = render(tmp_path, "m", ag, drive="logic.collectorAttention = true", size=(300, 40))
    marker = [b for b in out["badges"] if b["name"] == "Collector needs attention"]
    assert len(marker) == 1 and marker[0]["bg"] == "#15171b"
    off = render(tmp_path / "off", "m", ag, size=(300, 40))
    assert not [b for b in off["badges"] if b["name"] == "Collector needs attention"]


def test_marker_and_card_colors_meet_contrast():
    warning, ui = "#f5a524", _ui()
    assert ratio(warning, ui["panel"]) >= 3 and ratio(ui["panel"], warning) >= 4.5  # forma sobre a pílula; "!" sobre o selo
    assert ratio(warning, ui["card"]) >= 3  # borda do card
    assert ratio(ui["fg"], ui["card"]) >= 4.5 and ratio(ui["muted"], ui["card"]) >= 4.5


def test_js_status_helpers(tmp_path):
    out = js(tmp_path, """({
      cmd: CJ.buildStatusCommand(CJ.scriptPath("file:///home/a%20b/%C3%81rea/collector-installer.py"), "1.2.0", "~/x'y"),
      att: ["ausente", "desatualizado", "python_indisponivel", "mais_novo", "ok"].map(function (s) { return CJ.needsAttention({state: s}) }),
      nul: CJ.needsAttention(null), bad: CJ.parseStatus("{", 0), str: CJ.parseStatus('{"state":"ok","installed":"1.2.0"}', 0)})""")
    assert out["cmd"] == "python3 '/home/a b/Área/collector-installer.py' status --required '1.2.0' --collector-path '~/x'\\''y'"
    assert out["att"] == [True, True, True, False, False] and out["nul"] is False and out["bad"] is None
    assert out["str"] == {"state": "ok", "installed": "1.2.0", "required": "", "message": ""}


def test_main_checks_status_cheaply_with_packaged_script_and_metadata_version():
    main = (UI_DIR / "main.qml").read_text()
    assert 'Qt.resolvedUrl("../code/collector-installer.py")' in main and "Plasmoid.metaData.version" in main
    assert "Plasmoid.configuration.collectorPath" in main and "< 30000" in main
    assert (UI_DIR.parent / "code" / "collector-installer.py").is_file()
    assert "checkCollector" not in main.split("id: providerRefreshScheduler")[1].split("// Execução da CLI")[0]  # nunca no laço de 15 s


# ---- Ticket 50: botão, confirmação e instalação (o DataSource do install vive no main.qml; aqui o plasmoidItem é falso) ----
INSTALL = """
logic.collectorStatus = Collector.parseStatus(%s, 0); wait(100)
var ok = function () { return buttons().map(function (b) { return b.text }) }
%s
"""


def inst(tmp_path, drive, state="ausente", **kw):
    raw = json.dumps(st(state, installed="1.0.0" if state == "desatualizado" else None))
    return popup(tmp_path, "inst", drive=INSTALL % (json.dumps(raw), drive), size=(460, 900), **kw)


def test_nothing_installs_on_startup_timer_or_opening_the_popup(tmp_path):
    out = inst(tmp_path, "wait(700); obs('conf', vis('collectorConfirm').length)")
    assert "install" not in out["calls"] and out["conf"] == 0
    main = (UI_DIR / "main.qml").read_text()
    assert main.count("installCollector()") == 1 and main.count("installSource.connectSource") == 1  # só a função, sem gatilho próprio
    assert "installCollector(" not in main.split("function installCollector")[0]
    assert "installCollector(" not in main.split("id: installSource")[1].split("Timer {", 1)[1]  # nenhum Timer chama


def test_click_opens_confirmation_with_exact_details_and_cancel_has_initial_focus(tmp_path):
    out = inst(tmp_path, """
    btn("Install collector").click(); wait(50)
    obs('conf', vis('collectorConfirm').length); obs('title', txt('collectorConfirmTitle')); obs('det', txt('collectorConfirmDetails'))
    obs('focus', focusName()); obs('hidden', btn("Install collector") === undefined)
    """)
    assert out["conf"] == 1 and out["title"] == ["Install collector version 1.2.0?"] and "install" not in out["calls"]
    d = out["det"][0]
    assert "plasma-ai-usage-collector version 1.2.0 will be downloaded from PyPI" in d
    assert "~/.local/share/plasma-ai-usage/venv" in d and "shortcut in ~/.local/bin" in d and "No sudo" in d and "system Python is not changed" in d
    assert out["focus"] == "Cancel" and out["hidden"]


def test_update_title_for_desatualizado(tmp_path):
    out = inst(tmp_path, "btn('Update collector').click(); wait(50); obs('title', txt('collectorConfirmTitle'))", state="desatualizado")
    assert out["title"] == ["Update collector to version 1.2.0?"]


def test_cancel_button_and_escape_run_nothing_and_keep_the_popup_open(tmp_path):
    out = inst(tmp_path, """
    btn("Install collector").click(); wait(50); btn("Cancel").click(); wait(50)
    obs('after1', vis('collectorConfirm').length); obs('back', btn("Install collector") !== undefined)
    btn("Install collector").click(); wait(50); tc.keyClick(Qt.Key_Escape); wait(50)
    obs('after2', vis('collectorConfirm').length)
    """)
    assert out["after1"] == 0 and out["back"] and out["after2"] == 0
    out = inst(tmp_path / "root", "btn('Install collector').click(); wait(50); f.forceActiveFocus(); tc.keyClick(Qt.Key_Escape); wait(50); obs('c', vis('collectorConfirm').length)")
    assert out["c"] == 0 and "close" not in out["calls"]  # Esc com o foco fora dos botões também só cancela a pergunta
    assert "install" not in out["calls"] and "close" not in out["calls"] and out["cmds"] == []  # Esc cancela a pergunta, não fecha o popup


def test_enter_confirms_only_with_focus_on_install_and_runs_exactly_once(tmp_path):
    out = inst(tmp_path, """
    btn("Install collector").click(); wait(50)
    tc.keyClick(Qt.Key_Return); wait(50)       // foco inicial no Cancel: Enter cancela, não instala
    obs('afterEnterOnCancel', logic.calls.indexOf('install') >= 0)
    btn("Install collector").click(); wait(50)
    var c = btn("Install"); c.forceActiveFocus(); tc.keyClick(Qt.Key_Return); tc.keyClick(Qt.Key_Return); c.click(); wait(50)
    obs('conf', vis('collectorConfirm').length)
    """)
    assert out["afterEnterOnCancel"] is False
    assert out["calls"].count("install") == 1 and out["conf"] == 0


def test_double_click_on_confirm_does_not_duplicate_and_running_disables_button(tmp_path):
    out = inst(tmp_path, """
    btn("Install collector").click(); wait(50)
    var c = btn("Install"); c.click(); c.click(); wait(50)
    logic.collectorInstall = {state: "running", step: "download"}; wait(50)
    var b = btn("Installing the collector…"); obs('dis', b.enabled); b.click(); wait(50)
    obs('bar', vis('collectorInstallBar').length); obs('step', txt('collectorInstallStep')); obs('conf', vis('collectorConfirm').length)
    """)
    assert out["calls"].count("install") == 1 and out["dis"] is False and out["bar"] == 1 and out["conf"] == 0
    assert out["step"] == ["Downloading the package"]


def test_invalid_widget_version_disables_the_button_and_never_confirms(tmp_path):
    out = inst(tmp_path, """
    logic.widgetVersion = "1.2.0; rm -rf ~"; wait(50)
    var b = btn("Install collector"); obs('en', b.enabled); b.click(); wait(50)
    obs('conf', vis('collectorConfirm').length)
    """)
    assert out["en"] is False and out["conf"] == 0 and "install" not in out["calls"]


CAUSES = {
    "python_indisponivel": "Python 3 with venv support is not available. Install it and try again.",
    "rede": "Could not download the package. Check your internet connection and try again.",
    "versao_inexistente": "This collector version is not available on PyPI yet.",
    "permissao": "Permission denied while writing to the installation folders.",
    "conflito_em_local_bin": "Another file already exists in ~/.local/bin and was not overwritten.",
    "verificacao": "The installed collector did not pass the verification check.",
    "falha": "The installation failed.",
}


@pytest.mark.parametrize("cause", CAUSES)
def test_failure_shows_translated_cause_message_log_and_try_again(tmp_path, cause):
    out = inst(tmp_path, """
    logic.collectorInstall = {state: "error", cause: "%s", message: "<b>x</b> boom", log: ["<b>x</b>", "linha 2"], failedStep: "download"}; wait(100)
    obs('cause', txt('collectorInstallCause')); obs('msg', txt('collectorInstallMessage')); obs('log', txt('collectorInstallLog'))
    obs('logFmt', named('collectorInstallLog')[0].textFormat === Text.PlainText); obs('btns', ok())
    btn("Try again").click(); wait(50); obs('conf', vis('collectorConfirm').length)
    """ % cause)
    assert out["cause"] == [CAUSES[cause]]
    assert out["msg"] == ["Details: <b>x</b> boom\nStopped during: Downloading the package"]
    assert out["log"] == ["<b>x</b>\nlinha 2"] and out["logFmt"] and "Try again" in out["btns"]
    assert out["conf"] == 1 and "install" not in out["calls"]  # tentar de novo também pede confirmação


@pytest.mark.parametrize("state", ["python_indisponivel", "mais_novo", "ok"])
def test_no_install_button_for_states_without_action(tmp_path, state):
    out = inst(tmp_path, """
    logic.collectorInstall = {state: "error", cause: "rede", message: "m", log: ["l"]}; wait(50)
    obs('btns', ok()); obs('err', vis('collectorInstallError').length); obs('conf', vis('collectorConfirm').length)
    """, state=state)
    assert not [b for b in out["btns"] if "nstall" in b or "pdate collector" in b or "Try again" in b]
    assert out["err"] == 0 and out["conf"] == 0


def test_install_command_is_strict_and_quoted(tmp_path):
    out = js(tmp_path, """({
      ok: CJ.buildInstallCommand("/home/a b/x/collector-installer.py", "1.2.0"),
      bad: ["", "1.2", "1.2.0;rm -rf ~", "1.2.0\\n", "$(id)", "1.2.0 --index-url http://x", "http://x/y.whl", null, undefined, "v1.2.0", "1.2.x"].map(function (v) { return CJ.buildInstallCommand("/s.py", v) })})""")
    assert out["ok"] == "python3 '/home/a b/x/collector-installer.py' install --version '1.2.0'"
    assert out["bad"] == [""] * 11


def test_parse_install_requires_exit_zero_and_final_ok_line(tmp_path):
    lines = '{"step":"venv","status":"start","message":""}\n{"step":"venv","status":"ok","message":""}\n{"step":"download","status":"error","message":"x"}\n'
    out = js(tmp_path, """({
      ok: CJ.parseInstall(%(l)s + '{"result":"ok","cause":null,"message":"feito","log":[]}', 0),
      okButExit1: CJ.parseInstall('{"result":"ok","cause":null,"message":"m","log":[]}', 1),
      noFinal: CJ.parseInstall(%(l)s, 0), py127: CJ.parseInstall("", 127),
      weird: CJ.parseInstall('{"result":"error","cause":"evil","message":5,"log":"nao lista"}', 1),
      err: CJ.parseInstall(%(l)s + '{"result":"error","cause":"rede","message":"sem rede","log":["a","b"]}', 1),
      cur: [CJ.currentStep('{"step":"venv","status":"start","message":""}\\n'), CJ.currentStep('{"step":"venv","status":"ok","message":""}'), CJ.currentStep("")]})"""
              % {"l": json.dumps(lines)})
    assert out["ok"]["ok"] is True and out["okButExit1"]["ok"] is False and out["okButExit1"]["cause"] == "falha"
    assert out["noFinal"]["ok"] is False and out["noFinal"]["cause"] == "falha" and out["py127"]["cause"] == "python_indisponivel"
    assert out["weird"]["cause"] == "falha" and out["weird"]["log"] == [] and out["weird"]["message"] == "5"
    assert out["err"] == {"ok": False, "cause": "rede", "message": "sem rede", "log": ["a", "b"], "failedStep": "download"}
    assert out["cur"] == ["venv", "", ""]


def test_main_install_wiring_is_guarded_and_refreshes_after_success():
    main = (UI_DIR / "main.qml").read_text()
    fn = main.split("function installCollector")[1].split("Plasma5Support.DataSource")[0]
    assert 'state === "running") return' in fn and "Collector.buildInstallCommand(script, root.widgetVersion)" in fn
    ds = main.split("id: installSource")[1].split("Timer {")[0]
    assert 'data["exit code"] === undefined' in ds and "root.checkCollector()" in ds and "root.collectorCheckedAt = 0" in ds
    assert 'verifying: true' in ds and 'cause: "verificacao"' in main.split("id: statusCheckSource")[1].split("Timer {")[0]  # só volta a idle após o recheck
    assert "root.runCollectorRefresh(null, false)" in ds and "--force-renew" not in ds


def test_install_ui_colors_meet_contrast():
    ui = _ui()
    assert ratio(ui["fg"], ui["card"]) >= 4.5 and ratio(ui["muted"], ui["card"]) >= 4.5  # mensagem, log e passo (muted) sobre o card
