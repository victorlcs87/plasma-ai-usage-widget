"""Instalador do Coletor (Spec 09, ticket 75): subcomando `update`.

Mesmo estilo do install: HOME temporário, wheel e .plasmoid locais (PLASMA_AI_INSTALLER_FIND_LINKS e
PLASMA_AI_INSTALLER_PLASMOID_DIR) e um kpackagetool6 falso no PATH que registra os argumentos.
"""

from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
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
