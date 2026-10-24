"""Instalador do Coletor (Spec 07, ticket 51): subcomando `install`.

Roda o script como processo, em HOME temporário, com o .whl local como índice (PLASMA_AI_INSTALLER_FIND_LINKS):
nunca toca no HOME real nem usa a rede.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plasmoid" / "contents" / "code" / "collector-installer.py"
from ai_usage_collector import __version__ as VERSION


@pytest.fixture(scope="session")
def wheelhouse(tmp_path_factory):
    """Diretório com o .whl real do Coletor, gerado por scripts/package-release.sh (build offline)."""
    out = tmp_path_factory.mktemp("dist")
    env = dict(os.environ, PYTHON=sys.executable, BUILD_ARGS="--no-isolation")
    r = subprocess.run([str(ROOT / "scripts" / "package-release.sh"), str(out)], env=env, capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.fixture(scope="session")
def old_wheelhouse(tmp_path_factory):
    """Wheel mínimo 1.0.0 (mesmo módulo e scripts), para testar a atualização."""
    out = tmp_path_factory.mktemp("old")
    di = "plasma_ai_usage_collector-1.0.0.dist-info"
    with zipfile.ZipFile(out / "plasma_ai_usage_collector-1.0.0-py3-none-any.whl", "w") as z:
        z.writestr("ai_usage_collector/__init__.py", "")
        z.writestr("ai_usage_collector/cli.py", "def main():\n    print('ai-usage-collector 1.0.0')\n")
        z.writestr("ai_usage_collector/session_state.py", "def states_main():\n    print('x')\n")
        z.writestr(di + "/METADATA", "Metadata-Version: 2.1\nName: plasma-ai-usage-collector\nVersion: 1.0.0\n")
        z.writestr(di + "/WHEEL", "Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(di + "/entry_points.txt", "[console_scripts]\nai-usage-collector = ai_usage_collector.cli:main\n"
                   "ai-usage-session-state = ai_usage_collector.session_state:states_main\n")
        z.writestr(di + "/RECORD", "")
    return out


class Sandbox:
    def __init__(self, tmp_path, find_links):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin = tmp_path / "pybin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.env = {"HOME": str(self.home), "PATH": str(self.bin),
                    "PLASMA_AI_INSTALLER_FIND_LINKS": str(find_links)}
        self.venv = self.home / ".local/share/plasma-ai-usage/venv"
        self.link = self.home / ".local/bin/ai-usage-collector"

    def popen(self, *args, **env):
        return subprocess.Popen([sys.executable, str(SCRIPT), *args], env={**self.env, **env}, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)

    def install(self, version=VERSION, **env):
        p = self.popen("install", "--version", version, **env)
        out, err = p.communicate(timeout=120)
        lines = [json.loads(line) for line in out.splitlines()]
        return p.returncode, lines, err

    def no_leftovers(self):
        return not self.venv.exists() and not self.link.exists() and not self.link.is_symlink()


@pytest.fixture
def sb(tmp_path, wheelhouse):
    return Sandbox(tmp_path, wheelhouse)


def final(lines):
    assert "result" in lines[-1]
    return lines[-1]


def test_sucesso_cria_venv_atalho_e_versao_bate(sb):
    code, lines, _ = sb.install()
    assert code == 0
    assert final(lines) == {"result": "ok", "cause": None, "message": final(lines)["message"], "log": []}
    steps = [(x["step"], x["status"]) for x in lines[:-1]]
    assert steps == [("venv", "start"), ("venv", "ok"), ("download", "start"), ("download", "ok"),
                     ("install", "start"), ("install", "ok"), ("link", "start"), ("link", "ok"),
                     ("verify", "start"), ("verify", "ok")]
    assert all(set(x) == {"step", "status", "message"} for x in lines[:-1])
    assert sb.link.is_symlink() and os.readlink(sb.link) == str(sb.venv / "bin/ai-usage-collector")
    assert (sb.home / ".local/bin/ai-usage-session-state").is_symlink()
    r = subprocess.run([str(sb.link), "--version"], capture_output=True, text=True, env=sb.env)
    assert r.stdout.strip() == f"ai-usage-collector {VERSION}"


def test_versao_inexistente_limpa_tudo(sb):
    code, lines, _ = sb.install("9.9.9")
    assert code != 0
    f = final(lines)
    assert (f["result"], f["cause"]) == ("error", "versao_inexistente")
    assert any("No matching distribution" in x or "Could not find" in x for x in f["log"])
    assert sb.no_leftovers()
    assert {"step": "download", "status": "error"}.items() <= lines[-2].items()


def test_rede_simulada(sb):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # porta fechada
    sb.env.pop("PLASMA_AI_INSTALLER_FIND_LINKS")
    code, lines, _ = sb.install(PLASMA_AI_INSTALLER_INDEX=f"http://127.0.0.1:{port}/simple")
    assert code != 0
    assert final(lines)["cause"] == "rede", final(lines)
    assert sb.no_leftovers()


def test_pip_ignora_pip_env_e_pip_conf_do_usuario(sb, wheelhouse):
    """PIP_INDEX_URL malicioso, PIP_FIND_LINKS e pip.conf do usuário não valem; proxy/cert da allowlist sim."""
    h = _Hang()
    try:
        (sb.home / ".config/pip").mkdir(parents=True)
        (sb.home / ".config/pip/pip.conf").write_text(f"[global]\nindex-url = {h.url}\nfind-links = {wheelhouse}\n")
        sb.env.pop("PLASMA_AI_INSTALLER_FIND_LINKS")
        # sem override o índice é o PyPI; o proxy (allowlist) é repassado e recusa a conexão, sem sair da máquina
        code, lines, _ = sb.install(PIP_INDEX_URL=h.url, PIP_EXTRA_INDEX_URL=h.url, PIP_FIND_LINKS=str(wheelhouse),
                                    PIP_CONFIG_FILE=str(sb.home / ".config/pip/pip.conf"),
                                    HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")
        assert code != 0 and final(lines)["cause"] == "rede", final(lines)
        assert not h.got.is_set()  # o índice do ambiente nunca foi consultado
        assert "Connection refused" in "\n".join(final(lines)["log"])  # tentou o PyPI pelo proxy (porta 9), não o índice do ambiente
    finally:
        h.close()


def test_log_sem_caminho_pessoal_nem_credencial(sb):
    code, lines, _ = sb.install("9.9.9", PLASMA_AI_INSTALLER_FIND_LINKS=str(sb.home / "x"))
    blob = json.dumps(final(lines))
    assert str(sb.home) not in blob


@pytest.mark.parametrize("bad", ["latest", "1.2", "1.2.3 ", "1.2.3\n", "1.2.3rc1", ">=1.0", "1.2.3; touch pwn",
                                 "$(touch pwn)", "1.2.3 --index-url http://x", "١.٢.٣", "", "1.2.3.4"])
def test_versao_invalida_nao_toca_em_nada(sb, bad):
    code, lines, _ = sb.install(bad)
    assert code != 0 and len(lines) == 1
    assert (final(lines)["result"], final(lines)["cause"]) == ("error", "falha")
    assert not (sb.home / ".local").exists() and not (sb.home / "pwn").exists()


@pytest.mark.parametrize("extra", [["--index-url", "http://x/simple"], ["--find-links", "/tmp"],
                                   ["--version", "1.1.1"], ["--extra-index-url=http://x"]])
def test_nao_aceita_indice_por_argumento(sb, extra):
    p = sb.popen("install", "--version", VERSION, *extra)
    out, _ = p.communicate(timeout=30)
    assert p.returncode != 0
    assert json.loads(out.splitlines()[-1])["result"] == "error"
    assert not (sb.home / ".local").exists()


def test_conflito_arquivo_regular(sb):
    sb.link.parent.mkdir(parents=True)
    sb.link.write_text("meu coletor\n")
    code, lines, _ = sb.install()
    assert code != 0 and final(lines)["cause"] == "conflito_em_local_bin"
    assert sb.link.read_text() == "meu coletor\n" and not sb.link.is_symlink()
    assert not sb.venv.exists()


def test_conflito_symlink_externo(sb, tmp_path):
    ext = tmp_path / "pipx" / "ai-usage-collector"
    ext.parent.mkdir()
    ext.write_text("#!/bin/sh\necho ai-usage-collector 1.1.1\n")
    ext.chmod(0o755)
    sb.link.parent.mkdir(parents=True)
    sb.link.symlink_to(ext)
    code, lines, _ = sb.install()
    assert code != 0 and final(lines)["cause"] == "conflito_em_local_bin"
    assert os.readlink(sb.link) == str(ext)
    assert not sb.venv.exists()


def test_conflito_na_segunda_ferramenta_nao_deixa_nada_novo(sb):
    other = sb.home / ".local/bin/ai-usage-session-state"
    other.parent.mkdir(parents=True)
    other.write_text("meu\n")
    code, lines, _ = sb.install()
    assert code != 0 and final(lines)["cause"] == "conflito_em_local_bin"
    assert other.read_text() == "meu\n" and not sb.link.is_symlink() and not sb.venv.exists()


def test_idempotente_reutiliza_venv_integro(sb):
    assert sb.install()[0] == 0
    marcador = sb.venv / "marcador"
    marcador.write_text("x")
    code, lines, _ = sb.install()
    assert code == 0 and final(lines)["result"] == "ok"
    assert marcador.exists()  # venv íntegro não é recriado
    assert subprocess.run([str(sb.link), "--version"], capture_output=True, text=True, env=sb.env).stdout.strip() == \
        f"ai-usage-collector {VERSION}"


def test_falha_nao_apaga_venv_preexistente_integro(sb):
    assert sb.install()[0] == 0
    code, lines, _ = sb.install("9.9.9")
    assert code != 0 and final(lines)["cause"] == "versao_inexistente"
    assert subprocess.run([str(sb.link), "--version"], capture_output=True, text=True, env=sb.env).stdout.strip() == \
        f"ai-usage-collector {VERSION}"


def test_atualizacao_preserva_dados_do_usuario(tmp_path, wheelhouse, old_wheelhouse):
    sb = Sandbox(tmp_path, old_wheelhouse)
    code, _, _ = sb.install("1.0.0")
    assert code == 0
    assert subprocess.run([str(sb.link), "--version"], capture_output=True, text=True, env=sb.env).stdout.strip() == \
        "ai-usage-collector 1.0.0"
    sentinelas = {sb.home / ".config/plasma-ai-usage/config.json": "cfg",
                  sb.home / ".cache/plasma-ai-usage/history/h.json": "hist",
                  sb.home / ".config/plasma-ai-usage/accounts/a.json": "conta"}
    for p, t in sentinelas.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    code, lines, _ = sb.install(VERSION, PLASMA_AI_INSTALLER_FIND_LINKS=str(wheelhouse))
    assert code == 0, lines
    assert subprocess.run([str(sb.link), "--version"], capture_output=True, text=True, env=sb.env).stdout.strip() == \
        f"ai-usage-collector {VERSION}"
    assert {p: p.read_text() for p in sentinelas} == sentinelas
    escritos = {str(p.relative_to(sb.home)) for p in sb.home.rglob("*") if p.is_file()
                and ".local/share/plasma-ai-usage" not in str(p) and ".local/bin" not in str(p)
                and ".cache/pip" not in str(p) and ".cache/plasma-ai-usage/history/h.json" not in str(p)}
    assert escritos <= {".config/plasma-ai-usage/config.json", ".config/plasma-ai-usage/accounts/a.json"}


class _Hang:
    """Índice falso que aceita a conexão e nunca responde (mantém o pip preso)."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.url = f"http://127.0.0.1:{self.srv.getsockname()[1]}/simple"
        self.got = threading.Event()
        self.conns = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.conns.append(c)
            self.got.set()

    def close(self):
        self.srv.close()
        for c in self.conns:
            c.close()


@pytest.fixture
def hang(sb):
    h = _Hang()
    sb.env = {k: v for k, v in sb.env.items() if k != "PLASMA_AI_INSTALLER_FIND_LINKS"}
    sb.env.update(PLASMA_AI_INSTALLER_INDEX=h.url)
    yield h
    h.close()


def _wait_download(p, hang):
    first = json.loads(p.stdout.readline())
    while not (first["step"], first["status"]) == ("download", "start"):
        first = json.loads(p.stdout.readline())
    assert hang.got.wait(30)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_interrupcao_limpa_e_nao_bloqueia_a_proxima(sb, hang, wheelhouse, sig):
    p = sb.popen("install", "--version", VERSION)
    _wait_download(p, hang)
    p.send_signal(sig)
    out, _ = p.communicate(timeout=30)
    assert p.returncode != 0
    f = json.loads(out.splitlines()[-1])
    assert (f["result"], f["cause"]) == ("error", "falha")
    assert sb.no_leftovers()
    # a tentativa seguinte funciona (lock solto, nada sobrou)
    sb.env.pop("PLASMA_AI_INSTALLER_INDEX")
    sb.env.update(PLASMA_AI_INSTALLER_FIND_LINKS=str(wheelhouse))
    assert sb.install()[0] == 0


def test_instalacao_simultanea_e_recusada(sb, hang):
    a = sb.popen("install", "--version", VERSION)
    _wait_download(a, hang)
    code, lines, _ = sb.install()
    assert code != 0
    assert (final(lines)["cause"], "andamento" in final(lines)["message"]) == ("falha", True)
    assert a.poll() is None  # a primeira segue viva
    a.terminate()
    a.communicate(timeout=30)


def test_kill_9_nao_deixa_lock_preso(sb, hang, wheelhouse):
    a = sb.popen("install", "--version", VERSION)
    _wait_download(a, hang)
    a.kill()  # sem chance de limpar: sobra venv parcial e o pip órfão
    a.communicate(timeout=30)
    sb.env.pop("PLASMA_AI_INSTALLER_INDEX")
    sb.env.update(PLASMA_AI_INSTALLER_FIND_LINKS=str(wheelhouse))
    code, lines, _ = sb.install()
    assert code == 0, lines


def test_python_indisponivel_sem_venv(sb):
    (sb.bin / "python3").unlink()
    (sb.bin / "python3").write_text("#!/bin/sh\nexit 1\n")
    (sb.bin / "python3").chmod(0o755)
    code, lines, _ = sb.install()
    f = final(lines)
    assert code != 0 and f["cause"] == "python_indisponivel"
    assert "python3" in f["message"]
    assert not (sb.home / ".local/bin").exists() and not sb.venv.exists()


def test_python_ausente(sb):
    (sb.bin / "python3").unlink()
    code, lines, _ = sb.install()
    assert code != 0 and final(lines)["cause"] == "python_indisponivel"


def test_venv_quebrado_de_tentativa_anterior_e_refeito(sb):
    (sb.venv / "bin").mkdir(parents=True)
    (sb.venv / "pyvenv.cfg").write_text("home = /nada\n")
    code, lines, _ = sb.install()
    assert code == 0, lines


def test_destino_do_venv_que_nao_e_venv_nao_e_apagado(sb):
    sb.venv.mkdir(parents=True)
    (sb.venv / "dados.txt").write_text("meus dados")
    code, lines, _ = sb.install()
    assert code != 0 and final(lines)["cause"] == "falha"
    assert (sb.venv / "dados.txt").read_text() == "meus dados"


def test_permissao_negada(sb):
    if os.geteuid() == 0:
        pytest.skip("root ignora permissões")
    (sb.home / ".local").mkdir()
    (sb.home / ".local").chmod(0o500)
    try:
        code, lines, _ = sb.install()
    finally:
        (sb.home / ".local").chmod(0o700)
    assert code != 0 and final(lines)["cause"] == "permissao"


def test_codigo_sem_sudo_nem_shell():
    src = SCRIPT.read_text()
    for proibido in ("sudo", "shell=True", "os.system", "os.popen", "pkexec"):
        assert proibido not in src


def test_status_continua_funcionando(sb):
    r = subprocess.run([sys.executable, str(SCRIPT), "status", "--required", VERSION], env=sb.env,
                       capture_output=True, text=True)
    assert json.loads(r.stdout)["state"] in {"ausente", "python_indisponivel"}
