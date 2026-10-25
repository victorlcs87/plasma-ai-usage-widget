"""Instalador do Coletor (Spec 09, ticket 75): subcomando `update`.

Mesmo estilo do install: HOME temporário, wheel e .plasmoid locais (PLASMA_AI_INSTALLER_FIND_LINKS e
PLASMA_AI_INSTALLER_PLASMOID_DIR) e um kpackagetool6 falso no PATH que registra os argumentos.
"""

from __future__ import annotations

import importlib.util
import json
import signal
import zipfile
import hashlib
import subprocess
import time
import urllib.request

import pytest

from test_collector_installer_install import (  # noqa: F401  (fixtures e helpers compartilhados)
    SCRIPT, VERSION, Sandbox, _Hang, _wait_download, final, old_wheelhouse, wheelhouse,
)

PLASMOID = "org.kde.plasma.aiusage.plasmoid"


class UpdateSandbox(Sandbox):
    def __init__(self, tmp_path, find_links, plasmoid_dir, kpkg_exit=0):
        super().__init__(tmp_path, find_links)
        self.env["PLASMA_AI_INSTALLER_PLASMOID_DIR"] = str(plasmoid_dir)
        self.kpkg_log = tmp_path / "kpkg.log"
        if kpkg_exit is not None:
            fake = self.bin / "kpackagetool6"
            fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {self.kpkg_log}\necho falhou >&2\nexit {kpkg_exit}\n')
            fake.chmod(0o755)

    def update(self, version=VERSION, **env):
        p = self.popen("update", "--version", version, **env)
        out, err = p.communicate(timeout=120)
        return p.returncode, [json.loads(line) for line in out.splitlines()], err

    def kpkg_calls(self):
        return self.kpkg_log.read_text().splitlines() if self.kpkg_log.exists() else []


@pytest.fixture
def ub(tmp_path, wheelhouse):
    return UpdateSandbox(tmp_path, wheelhouse, wheelhouse)


@pytest.fixture
def hang(ub):
    h = _Hang()
    ub.env = {k: v for k, v in ub.env.items() if k != "PLASMA_AI_INSTALLER_FIND_LINKS"}
    ub.env["PLASMA_AI_INSTALLER_INDEX"] = h.url
    yield h
    h.close()


def test_sucesso(ub):
    code, lines, _ = ub.update()
    assert code == 0, lines
    assert final(lines)["result"] == "ok" and final(lines)["cause"] is None
    steps = [(x["step"], x["status"]) for x in lines[:-1]]
    assert steps[-8:] == [("plasmoid_hash", "start"), ("plasmoid_hash", "ok"), ("plasmoid_download", "start"),
                          ("plasmoid_download", "ok"), ("plasmoid_verify", "start"), ("plasmoid_verify", "ok"),
                          ("plasmoid_install", "start"), ("plasmoid_install", "ok")]
    assert steps[0] == ("venv", "start") and ("verify", "ok") in steps
    (call,) = ub.kpkg_calls()
    assert call.startswith("-t Plasma/Applet --upgrade ") and call.endswith(PLASMOID)
    r = subprocess.run([str(ub.link), "--version"], capture_output=True, text=True, env=ub.env)
    assert r.stdout.strip() == f"ai-usage-collector {VERSION}"


def test_hash_divergente_nao_toca_no_plasmoid(tmp_path, wheelhouse):
    adulterado = tmp_path / "adulterado"
    adulterado.mkdir()
    (adulterado / PLASMOID).write_bytes((wheelhouse / PLASMOID).read_bytes() + b"x")
    ub = UpdateSandbox(tmp_path, wheelhouse, adulterado)
    code, lines, _ = ub.update()
    assert code != 0 and final(lines)["cause"] == "verificacao"
    assert lines[-2]["step"] == "plasmoid_verify" and lines[-2]["status"] == "error"
    assert ub.kpkg_calls() == []
    assert ub.no_leftovers()


def test_falha_do_coletor_nao_toca_no_plasmoid(ub):
    code, lines, _ = ub.update("9.9.9")
    assert code != 0 and final(lines)["cause"] == "versao_inexistente"
    assert ub.kpkg_calls() == [] and ub.no_leftovers()


def test_kpackagetool_ausente_falha_cedo_sem_alterar_nada(tmp_path, wheelhouse):
    ub = UpdateSandbox(tmp_path, wheelhouse, wheelhouse, kpkg_exit=None)
    code, lines, _ = ub.update()
    assert code != 0 and final(lines)["cause"] == "kpackagetool"
    assert len(lines) == 1 and ub.no_leftovers()


def test_kpackagetool_falha(tmp_path, wheelhouse):
    ub = UpdateSandbox(tmp_path, wheelhouse, wheelhouse, kpkg_exit=3)
    code, lines, _ = ub.update()
    f = final(lines)
    assert code != 0 and f["cause"] == "kpackagetool" and "falhou" in f["log"]
    assert lines[-2]["step"] == "plasmoid_install"


def test_sem_hash_embutido_orienta_manual_e_nao_instala(tmp_path, old_wheelhouse, wheelhouse):
    ub = UpdateSandbox(tmp_path, old_wheelhouse, wheelhouse)
    code, lines, _ = ub.update("1.0.0")
    f = final(lines)
    assert code != 0 and f["cause"] == "sem_hash" and "manual" in f["message"]
    assert ub.kpkg_calls() == []


def test_sem_downgrade(tmp_path, wheelhouse, old_wheelhouse):
    ub = UpdateSandbox(tmp_path, wheelhouse, wheelhouse)
    assert ub.update()[0] == 0
    ub.kpkg_log.unlink()
    code, lines, _ = ub.update("1.0.0", PLASMA_AI_INSTALLER_FIND_LINKS=str(old_wheelhouse))
    assert code != 0 and final(lines)["cause"] == "falha" and "downgrade" in final(lines)["message"]
    assert ub.kpkg_calls() == []
    r = subprocess.run([str(ub.link), "--version"], capture_output=True, text=True, env=ub.env)
    assert r.stdout.strip() == f"ai-usage-collector {VERSION}"


@pytest.mark.parametrize("bad", ["latest", "1.2", "1.2.3rc1", "1.2.3; touch pwn", ""])
def test_versao_invalida(ub, bad):
    code, lines, _ = ub.update(bad)
    assert code != 0 and len(lines) == 1 and final(lines)["cause"] == "falha"
    assert not (ub.home / ".local").exists()


@pytest.mark.parametrize("extra", [["--url", "http://x/a.plasmoid"], ["--index-url", "http://x"], ["http://x"]])
def test_nao_aceita_url_nem_indice(ub, extra):
    p = ub.popen("update", "--version", VERSION, *extra)
    out, _ = p.communicate(timeout=30)
    assert p.returncode != 0 and json.loads(out.splitlines()[-1])["result"] == "error"
    assert not (ub.home / ".local").exists()


def test_rede_ao_baixar_o_plasmoid(ub):
    del ub.env["PLASMA_AI_INSTALLER_PLASMOID_DIR"]
    code, lines, _ = ub.update(HTTPS_PROXY="http://127.0.0.1:9")
    assert code != 0 and final(lines)["cause"] == "rede"
    assert lines[-2]["step"] == "plasmoid_download" and ub.kpkg_calls() == []


def test_update_concorrente_e_recusado(ub, hang):
    a = ub.popen("update", "--version", VERSION)
    _wait_download(a, hang)
    code, lines, _ = ub.update()
    assert code != 0 and "andamento" in final(lines)["message"]
    a.terminate()
    a.communicate(timeout=30)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_sinal_no_meio_limpa_e_nao_toca_no_plasmoid(ub, hang, sig):
    p = ub.popen("update", "--version", VERSION)
    _wait_download(p, hang)
    p.send_signal(sig)
    out, _ = p.communicate(timeout=30)
    f = json.loads(out.splitlines()[-1])
    assert p.returncode != 0 and (f["result"], f["cause"]) == ("error", "falha")
    assert ub.no_leftovers() and ub.kpkg_calls() == []


@pytest.mark.parametrize("url,ok", [
    ("https://release-assets.githubusercontent.com/x/y", True),
    ("https://objects.githubusercontent.com/x", True),
    ("http://objects.githubusercontent.com/x", False),
    ("https://evil.example/x", False),
    ("https://github.com.evil.example/x", False),
    ("https://objects.githubusercontent.com@evil.example/x", False),
])
def test_redirect_so_para_hosts_da_lista(url, ok):
    spec = importlib.util.spec_from_file_location("collector_installer", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    req = urllib.request.Request("https://github.com/a")
    h = mod._SafeRedirect()
    if ok:
        assert h.redirect_request(req, None, 302, "Found", {}, url) is not None
    else:
        with pytest.raises(mod._Fail):
            h.redirect_request(req, None, 302, "Found", {}, url)


def _hang_kpkg(ub, marker):
    """kpackagetool6 falso que avisa que começou e trava (com um neto segurando o pipe)."""
    fake = ub.bin / "kpackagetool6"
    fake.write_text(f"#!/bin/sh\n: > {marker}\n/usr/bin/sleep 60 &\n/usr/bin/sleep 60\n")
    fake.chmod(0o755)


def test_kpackagetool_travado_vira_timeout_e_mantem_o_coletor(ub, tmp_path):
    _hang_kpkg(ub, tmp_path / "started")
    t0 = time.monotonic()
    code, lines, _ = ub.update(PLASMA_AI_INSTALLER_KPKG_TIMEOUT="1")
    f = final(lines)
    assert code != 0 and f["cause"] == "kpackagetool" and "tempo" in f["message"]
    assert lines[-2]["step"] == "plasmoid_install" and lines[-2]["status"] == "error"
    assert time.monotonic() - t0 < 50
    assert ub.link.is_symlink() and ub.venv.exists()


def test_sigterm_no_kpackagetool_mantem_o_coletor(ub, tmp_path):
    marker = tmp_path / "started"
    _hang_kpkg(ub, marker)
    p = ub.popen("update", "--version", VERSION)
    for _ in range(600):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
    p.terminate()
    out, _ = p.communicate(timeout=30)
    f = json.loads(out.splitlines()[-1])
    assert p.returncode != 0 and (f["result"], f["cause"]) == ("error", "falha")
    assert ub.link.is_symlink() and ub.venv.exists()


def test_download_lento_estoura_o_prazo_total(ub):
    code, lines, _ = ub.update(PLASMA_AI_INSTALLER_DOWNLOAD_DEADLINE="0")
    assert code != 0 and final(lines)["cause"] == "rede" and "tempo" in final(lines)["message"]
    assert lines[-2]["step"] == "plasmoid_download" and ub.kpkg_calls() == []


def test_plasmoid_acima_do_limite_vira_rede(tmp_path, wheelhouse):
    grande = tmp_path / "grande"
    grande.mkdir()
    with open(grande / PLASMOID, "wb") as f:
        f.truncate(20 * 1024 * 1024 + 1)
    ub = UpdateSandbox(tmp_path, wheelhouse, grande)
    code, lines, _ = ub.update()
    assert code != 0 and final(lines)["cause"] == "rede" and "máximo" in final(lines)["message"]
    assert lines[-2]["step"] == "plasmoid_download" and ub.kpkg_calls() == [] and ub.no_leftovers()


def test_plasmoid_local_ausente_vira_falha_clara(tmp_path, wheelhouse):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    ub = UpdateSandbox(tmp_path, wheelhouse, vazio)
    code, lines, _ = ub.update()
    assert code != 0 and final(lines)["cause"] == "falha" and "Erro de sistema" in final(lines)["message"]
    assert lines[-2]["step"] == "plasmoid_download" and ub.kpkg_calls() == []


def _fake_hash_wheelhouse(tmp_path):
    """Wheel 1.0.0 cujo `--plasmoid-sha256` imprime o que estiver em FAKE_HASH."""
    out = tmp_path / "fake"
    out.mkdir()
    di = "plasma_ai_usage_collector-1.0.0.dist-info"
    cli = ("import os, sys\ndef main():\n    print(os.environ.get('FAKE_HASH', '')) if '--plasmoid-sha256' in "
           "sys.argv else print('ai-usage-collector 1.0.0')\n")
    with zipfile.ZipFile(out / "plasma_ai_usage_collector-1.0.0-py3-none-any.whl", "w") as z:
        z.writestr("ai_usage_collector/__init__.py", "")
        z.writestr("ai_usage_collector/cli.py", cli)
        z.writestr("ai_usage_collector/session_state.py", "def states_main():\n    print('x')\n")
        z.writestr(di + "/METADATA", "Metadata-Version: 2.1\nName: plasma-ai-usage-collector\nVersion: 1.0.0\n")
        z.writestr(di + "/WHEEL", "Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(di + "/entry_points.txt", "[console_scripts]\nai-usage-collector = ai_usage_collector.cli:main\n"
                   "ai-usage-session-state = ai_usage_collector.session_state:states_main\n")
        z.writestr(di + "/RECORD", "")
    return out


@pytest.mark.parametrize("fake", ["MAIUSCULAS", "", "abc123", "g" * 64, "a" * 63])
def test_hash_do_coletor_invalido_ou_em_maiusculas_vira_sem_hash(tmp_path, wheelhouse, fake):
    real = hashlib.sha256((wheelhouse / PLASMOID).read_bytes()).hexdigest()
    fake = real.upper() if fake == "MAIUSCULAS" else fake
    ub = UpdateSandbox(tmp_path, _fake_hash_wheelhouse(tmp_path), wheelhouse)
    code, lines, _ = ub.update("1.0.0", FAKE_HASH=fake)
    assert code != 0 and final(lines)["cause"] == "sem_hash" and ub.kpkg_calls() == []
