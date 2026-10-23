"""Instalador do Coletor (Spec 07, ticket 50): subcomando `status`, em HOME temporário e PATH controlado."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "code" / "collector-installer.py"
_spec = importlib.util.spec_from_file_location("collector_installer", SCRIPT)
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)

PIPX_BIN = ".local/share/pipx/venvs/plasma-ai-usage-collector/bin"


def _exe(path: Path, body: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return str(path)


def _collector(path: Path, version: str = "1.1.1") -> str:
    return _exe(path, f'echo "ai-usage-collector {version}"')


@pytest.fixture
def env(tmp_path, monkeypatch):
    """HOME e PATH (bin vazio) só do teste; python3 falso utilizável por padrão."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    _exe(bin_dir / "python3", "exit 0")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(installer, "VERSION_TIMEOUT", 1)
    return home, bin_dir


def run(capsys, *args):
    assert installer.main(["x", "status", *args]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return json.loads(out)


def test_ok_no_path(env, capsys):
    home, bin_dir = env
    exe = _collector(bin_dir / "ai-usage-collector")
    r = run(capsys, "--required", "1.1.1")
    assert r == {"state": "ok", "installed": "1.1.1", "required": "1.1.1", "path": exe, "message": r["message"]}


def test_ausente_quando_nada_existe(env, capsys):
    r = run(capsys, "--required", "1.1.1")
    assert (r["state"], r["installed"], r["path"]) == ("ausente", None, None)


def test_desatualizado_e_mais_novo_comparam_numericamente(env, capsys):
    home, bin_dir = env
    _collector(bin_dir / "ai-usage-collector", "1.9.0")
    assert run(capsys, "--required", "1.10.0")["state"] == "desatualizado"  # 1.9 < 1.10 (string diria o contrário)
    assert run(capsys, "--required", "1.1.1")["state"] == "mais_novo"


def test_pre_release_e_menor_que_a_final(env, capsys):
    home, bin_dir = env
    _collector(bin_dir / "ai-usage-collector", "1.2.0rc1")
    r = run(capsys, "--required", "1.2.0")
    assert (r["state"], r["installed"]) == ("desatualizado", "1.2.0rc1")
    _collector(bin_dir / "ai-usage-collector", "1.2.0.dev3")
    assert run(capsys, "--required", "1.2.0")["state"] == "desatualizado"
    _collector(bin_dir / "ai-usage-collector", "1.2.0")
    assert run(capsys, "--required", "1.2.0rc1")["state"] == "mais_novo"


def test_python_indisponivel_quando_falta_venv_ou_python3(env, capsys):
    home, bin_dir = env
    _exe(bin_dir / "python3", "exit 1")  # import venv/ensurepip falha
    assert run(capsys, "--required", "1.1.1")["state"] == "python_indisponivel"
    (bin_dir / "python3").unlink()
    assert run(capsys, "--required", "1.1.1")["state"] == "python_indisponivel"


def test_python_indisponivel_nao_atrapalha_coletor_ok(env, capsys):
    home, bin_dir = env
    (bin_dir / "python3").unlink()
    _collector(bin_dir / "ai-usage-collector")
    assert run(capsys, "--required", "1.1.1")["state"] == "ok"


def test_local_bin_pipx_e_venv_de_desenvolvimento_contam_como_ok(env, capsys):
    home, bin_dir = env
    exe = _collector(home / ".local/bin/ai-usage-collector")
    assert run(capsys, "--required", "1.1.1")["path"] == exe
    os.unlink(exe)
    exe = _collector(home / PIPX_BIN / "ai-usage-collector")
    assert run(capsys, "--required", "1.1.1")["state"] == "ok"
    dev = _collector(home / "dev/.venv/bin/ai-usage-collector")
    os.unlink(exe)
    r = run(capsys, "--required", "1.1.1", "--collector-path", "~/dev/.venv/bin/ai-usage-collector")
    assert (r["state"], r["path"]) == ("ok", dev)


def test_ordem_path_antes_de_local_bin_antes_de_configurado(env, capsys):
    home, bin_dir = env
    _collector(home / ".local/bin/ai-usage-collector", "1.0.0")
    _collector(home / "x/c", "3.0.0")
    r = run(capsys, "--required", "1.1.1", "--collector-path", "~/x/c")
    assert r["installed"] == "1.0.0"  # ~/.local/bin vence o configurado
    _collector(bin_dir / "ai-usage-collector", "2.0.0")
    assert run(capsys, "--required", "1.1.1")["installed"] == "2.0.0"  # PATH vence


@pytest.mark.parametrize("body", ["while :; do :; done", "exit 3", 'echo "ai-usage-collector 1.1.1"; exit 2',
                                  "echo lixo qualquer", "echo ai-usage-collector abc", "",
                                  "printf '\\377\\376 ai-usage-collector 1.1.1\\n'"])
def test_version_que_trava_falha_ou_e_lixo_nao_e_confiavel(env, capsys, body):
    home, bin_dir = env
    exe = _exe(bin_dir / "ai-usage-collector", body)
    r = run(capsys, "--required", "1.1.1")
    assert r["state"] == "desatualizado" and r["installed"] is None and r["path"] == exe
    assert r["message"] and "lixo" not in r["message"]


def test_erro_inesperado_vira_json(env, capsys, monkeypatch):
    def boom(*_a):
        raise RuntimeError("segredo-xyz")

    monkeypatch.setattr(installer, "find_collector", boom)
    r = run(capsys, "--required", "1.1.1")
    assert r["state"] and r["message"] and "segredo-xyz" not in r["message"]


def test_entradas_invalidas_viram_json(env, capsys):
    assert run(capsys)["message"]  # sem --required
    assert run(capsys, "--required", "abc")["message"]
    assert installer.main(["x"]) == 0 and json.loads(capsys.readouterr().out)["message"]
    assert installer.main(["x", "install"]) == 0 and json.loads(capsys.readouterr().out)["message"]


def test_script_roda_como_processo_com_python_do_sistema(tmp_path):
    home = tmp_path / "h"
    bin_dir = tmp_path / "b"
    _collector(bin_dir / "ai-usage-collector", "9.9.9")
    env = {"HOME": str(home), "PATH": str(bin_dir)}
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "status", "--required", "1.1.1"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert p.returncode == 0 and p.stderr == ""
    assert json.loads(p.stdout)["state"] == "mais_novo"


def test_required_com_lixo_ao_redor_e_invalido(env, capsys):
    assert "inválida" in run(capsys, "--required", "abc1.2.3xyz")["message"]


def test_stdout_ascii_nao_quebra(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": str(tmp_path), "LC_ALL": "C", "PYTHONIOENCODING": "ascii"}
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "status", "--required", "1.1.1"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert p.returncode == 0 and json.loads(p.stdout)["state"] == "python_indisponivel"


def test_sem_sudo_nem_shell():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "sudo" not in src and "shell=True" not in src and "os.system" not in src
