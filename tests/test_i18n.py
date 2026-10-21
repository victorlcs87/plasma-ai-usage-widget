"""Ticket 40: catálogos de tradução (.pot/.po/.mo), mecanismo único tr() e nenhuma string visível fora de i18n.

Só fixtures e HOME falso: nada é instalado no sistema real.
"""
import gettext
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import i18n  # noqa: E402

UI = ROOT / "plasmoid" / "contents" / "ui"
PO = ROOT / "po"
DOMAIN = i18n.domain()
LANGS = ("pt_BR", "en")
PLACEHOLDER = re.compile(r"%\d")


def load(path):
    entries = i18n.parse_po(path.read_text(encoding="utf-8"))
    return entries[0], entries[1:]


def key(e):
    return (e["ctx"], e["id"], e["plural"])


def test_domain_comes_from_metadata_id():
    meta = json.loads((ROOT / "plasmoid" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["KPlugin"]["Id"] == "org.kde.plasma.aiusage"
    assert DOMAIN == "plasma_applet_org.kde.plasma.aiusage"
    assert (PO / f"{DOMAIN}.pot").is_file()


def test_every_i18n_call_has_a_literal_msgid_and_is_in_the_pot():
    entries, errors = i18n.extract()
    assert errors == []
    _, pot = load(PO / f"{DOMAIN}.pot")
    assert {key(e) for e in pot} == set(entries)
    assert len(pot) >= 300


def test_pot_is_deterministic_and_up_to_date():
    entries, _ = i18n.extract()
    fresh = i18n.write_po(i18n.header_for(""), i18n.template_entries(entries))
    assert (PO / f"{DOMAIN}.pot").read_text(encoding="utf-8") == fresh, "rode: python3 tools/i18n.py extract && python3 tools/i18n.py update"


@pytest.mark.parametrize("lang", LANGS)
def test_po_is_complete_with_same_placeholders_and_plurals(lang):
    _, pot = load(PO / f"{DOMAIN}.pot")
    _, po = load(PO / f"{lang}.po")
    assert [key(e) for e in po] == [key(e) for e in pot]
    for e in po:
        assert not e["fuzzy"], e["id"]
        n = 2 if e["plural"] is not None else 1
        assert sorted(e["str"]) == list(range(n)), e["id"]
        for i in range(n):
            s = e["str"][i]
            assert s.strip(), (lang, e["id"])
            src = e["id"] if i == 0 else e["plural"]
            assert sorted(PLACEHOLDER.findall(s)) == sorted(PLACEHOLDER.findall(src)), (lang, src, s)
            assert not re.search(r"<\s*[A-Za-z/]", s), f"{lang}: texto traduzido parece HTML (ToolTip é AutoText): {s!r}"


def test_en_is_the_source_language_and_pt_br_really_translates():
    _, en = load(PO / "en.po")
    assert all(e["str"][0] == e["id"] for e in en)
    _, pt = load(PO / "pt_BR.po")
    same = [e["id"] for e in pt if e["str"][0] == e["id"]]
    # só o que é igual nas duas línguas (símbolos, abreviações, nomes) pode repetir
    assert set(same) <= {"%1, %2", "normal", "%1min", "%1h %2min", "%1d %2h", "%1: —", "%1: %2", "%1 tokens", "30d", "3m", "12m",
                         "%1: %2 tokens", "Popup", "Teal", "Ring", "Logo", "%", "Popup:", "ID: %1"}, same


def test_no_visible_text_outside_i18n():
    assert i18n.visible_literals() == []


def test_translated_labels_are_plain_text():
    # Label com texto traduzido: textFormat PlainText (tradução nunca vira rich text)
    bad = []
    for path in sorted((ROOT / "plasmoid" / "contents").rglob("*.qml")):
        src = i18n.strip_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"(?<![\w.])(?:\w+\.)?(?:Label|Heading)\s*\{", src):
            i, depth = m.end(), 1
            while depth:
                depth += (src[i] == "{") - (src[i] == "}")
                i += 1
            body = src[m.end():i]
            if re.search(r"(?<![\w.])text\s*:", body) and "textFormat" not in body:
                bad.append(f"{path.name}:{src.count(chr(10), 0, m.start()) + 1}")
    assert bad == []


def test_plain_helpers_replace_all_placeholders_in_a_single_pass():
    # fallback de I18n.js sem i18n(): %N de uma vez, valor com "%2" ou "$&" não é reinterpretado
    out = _qml_eval_i18n('[I.tr("a %1 b %2 %1", "%2", "$&"), I.trp("%1 x", "%1 xs", 1), I.trp("%1 x", "%1 xs", 3), I.trc("c", "%1!", 7), I.tr("<b>%1</b>", "<i>")]')
    assert out == ["a %2 b $& %2", "1 x", "3 xs", "7!", "<b><i></b>"]


def _qml_eval_i18n(expr, extra=""):
    tmp = ROOT / ".pytest_i18n_tmp"
    tmp.mkdir(exist_ok=True)
    try:
        for f in ("I18n.js", "NotchModel.js", "Presets.js", "ViewPrefs.js"):
            shutil.copy(UI / f, tmp / f)
        (tmp / "t.qml").write_text('import QtQuick\nimport "I18n.js" as I\nimport "NotchModel.js" as N\n'
                                   f'Item {{ {extra}\n Component.onCompleted: {{ console.log("OUT " + JSON.stringify({expr})); Qt.quit() }} }}')
        res = subprocess.run(["qml6", str(tmp / "t.qml")], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1"))
        return json.loads((res.stdout + res.stderr).split("OUT ", 1)[1].splitlines()[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


needs_qml = pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")
test_plain_helpers_replace_all_placeholders_in_a_single_pass = needs_qml(test_plain_helpers_replace_all_placeholders_in_a_single_pass)


# ---- .mo ----

def compiled(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "tools" / "i18n.py"), "compile", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


@pytest.mark.parametrize("lang", LANGS)
def test_compiled_mo_loads_with_python_gettext(tmp_path, lang):
    root = compiled(tmp_path)
    mo = root / lang / "LC_MESSAGES" / f"{DOMAIN}.mo"
    assert mo.is_file()
    tr = gettext.translation(DOMAIN, str(root), languages=[lang])
    _, po = load(PO / f"{lang}.po")
    for e in po:
        if e["plural"] is None and e["ctx"] is None:
            assert tr.gettext(e["id"]) == e["str"][0]
        elif e["plural"] is not None:
            assert tr.ngettext(e["id"], e["plural"], 1) == e["str"][0]
            assert tr.ngettext(e["id"], e["plural"], 5) == e["str"][1]
    if lang == "pt_BR":
        assert tr.gettext("Settings") == "Configurações"
        assert tr.ngettext("%1 account", "%1 accounts", 2) == "%1 contas"
        assert tr.ngettext("%1 account", "%1 accounts", 0) == "%1 conta"  # pt_BR: plural=(n > 1)
    else:
        assert tr.gettext("Settings") == "Settings"


@pytest.mark.skipif(shutil.which("msgfmt") is None, reason="msgfmt not available")
@pytest.mark.parametrize("lang", LANGS)
def test_python_mo_matches_msgfmt(tmp_path, lang):
    ref = tmp_path / "ref.mo"
    subprocess.run(["msgfmt", "-o", str(ref), str(PO / f"{lang}.po")], check=True, capture_output=True)
    root = compiled(tmp_path / "ours")
    a = gettext.GNUTranslations(open(ref, "rb"))
    b = gettext.GNUTranslations(open(root / lang / "LC_MESSAGES" / f"{DOMAIN}.mo", "rb"))
    assert a._catalog == b._catalog


def test_mo_skips_fuzzy_and_empty_entries():
    ents = i18n.parse_po('msgid ""\nmsgstr ""\n"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n\n#, fuzzy\nmsgid "a"\nmsgstr "A"\n\nmsgid "b"\nmsgstr ""\n\nmsgid "c"\nmsgstr "C"\n')
    import io
    cat = gettext.GNUTranslations(io.BytesIO(i18n.build_mo(ents)))._catalog
    assert cat.get("c") == "C" and "a" not in cat and "b" not in cat


# ---- instalação (HOME falso) ----

def test_install_script_ships_compiled_catalogs(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
    env["HOME"] = str(home)
    res = subprocess.run([str(ROOT / "scripts" / "install-plasmoid.sh")], capture_output=True, text=True, env=env, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    installed = home / ".local" / "share" / "plasma" / "plasmoids" / "org.kde.plasma.aiusage"
    for lang in LANGS:
        mo = installed / "contents" / "locale" / lang / "LC_MESSAGES" / f"{DOMAIN}.mo"
        assert mo.is_file() and mo.stat().st_size > 1000, mo
    tr = gettext.translation(DOMAIN, str(installed / "contents" / "locale"), languages=["pt_BR"])
    assert tr.gettext("Settings") == "Configurações"
    assert not (ROOT / "plasmoid" / "contents" / "locale").exists(), "o .mo vai só para a cópia instalada"


# ---- as frases dos modelos JS com o catálogo carregado (placeholders na ordem certa) ----

def _catalog(lang):
    _, po = load(PO / f"{lang}.po")
    return {e["id"]: e["str"][0] for e in po if e["plural"] is None}


def _now():
    return datetime.now(timezone.utc)


def _fixture():
    from ai_usage_collector.contract import build_agent_account_status

    def iso(d):
        return (_now() + d).isoformat()
    acc = build_agent_account_status(
        provider="claude", account_id="a", label="A", source="auto", health={"status": "session_expired"}, is_active=True,
        native_window={"usage_percentage": 40.0, "release_time": iso(timedelta(hours=2, minutes=30, seconds=30)), "window_seconds": 18000},
        weekly_window={"usage_percentage": 70.0, "cycle_reset_time": iso(timedelta(days=3, hours=5, minutes=30)), "window_seconds": 604800})
    acc["stale"] = True
    acc["limit_changes"] = [{"kind": "x"}]
    return {"agents": {"claude": {"name": "Claude", "accounts": [acc]}}}


@needs_qml
@pytest.mark.parametrize("lang,needles", [
    ("pt_BR", ["Janela nativa: 40% — libera em 2h 30min", "Semanal: 70%", "dados desatualizados", "Sessão expirada"]),
    ("en", ["Native window: 40% — releases in 2h 30min", "Weekly: 70%", "stale data", "Session expired"]),
])
def test_model_phrases_follow_the_catalog(lang, needles):
    cfg = {"providerOrder": "claude", "hiddenProviders": "", "remaining": False, "date": False}
    now = int(_now().timestamp() * 1000)
    extra = f"property var cat: {json.dumps(_catalog(lang))}\n function t(s, a, b, c) {{ return I.fmt(cat[s] || s, [a, b, c]) }}"
    out = _qml_eval_i18n(f"N.tooltipText({json.dumps(_fixture())}, {json.dumps(cfg)}, t, {now})", extra)
    for n in needles:
        assert n in out, (lang, n, out)
    assert not PLACEHOLDER.search(out)
    view = _qml_eval_i18n(f"N.viewSummary(N.windowView({json.dumps(_fixture()['agents']['claude']['accounts'][0])}, "
                          f"{json.dumps(_fixture()['agents']['claude']['accounts'][0]['native_window'])}, 'native', {{remaining: true}}, {now}, t), true, t)", extra)
    assert not PLACEHOLDER.search(view), view
    assert ("restante" if lang == "pt_BR" else "remaining") in view


def test_every_placeholder_has_an_argument_in_its_call():
    # %N sem argumento correspondente apareceria cru na tela
    bad = []
    for path in i18n.source_files():
        src = i18n.strip_comments(path.read_text(encoding="utf-8"))
        for m in i18n.CALL.finditer(src):
            _, mi, pi = i18n.KEYWORDS[m.group(1)]
            args = i18n.parse_args(src, m.end())
            msg = i18n.literal(args[mi]) if mi < len(args) else None
            if msg is None or args == [""]:
                continue  # chamada sem argumentos literais (ex.: repasse); o extrator já acusa o que importa
            given = len(args) - (pi if pi is not None else mi) - 1 + (1 if pi is not None else 0)
            need = max([int(d) for d in re.findall(r"%(\d)", msg)] or [0])
            if given < need:
                bad.append((path.name, msg, given, need))
    assert bad == []
