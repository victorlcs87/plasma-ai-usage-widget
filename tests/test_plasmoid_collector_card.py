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
    assert out["actions"] == 1 and "Install" not in " ".join(out["buttons"])  # linha reservada para o ticket 50, sem botão
    assert 0 <= out["y"] < out["blockY"]


def test_desatualizado_shows_both_versions(tmp_path):
    out = card(tmp_path, st("desatualizado", installed="1.0.0"))
    assert out["title"] == ["⚠ Collector is older than the widget: 1.0.0 installed, 1.2.0 required"] and out["actions"] == 1


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
