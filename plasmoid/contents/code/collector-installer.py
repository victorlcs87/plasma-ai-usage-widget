#!/usr/bin/env python3
"""Instalador do Coletor (empacotado no Plasmoid). Só stdlib; roda com o python3 do sistema, sem o Coletor.

Uso: collector-installer.py status --required X.Y.Z [--collector-path CAMINHO]
Imprime sempre UMA linha de JSON e sai com 0:
  {"state": ausente|desatualizado|ok|mais_novo|python_indisponivel,
   "installed": "X.Y.Z"|null, "required": "X.Y.Z", "path": str|null, "message": str}
"""
import json
import os
import re
import shutil
import subprocess
import sys

BIN = "ai-usage-collector"
PIPX = "~/.local/share/pipx/venvs/plasma-ai-usage-collector/bin/" + BIN
VERSION_TIMEOUT = 5
_VER = re.compile(r"(\d+)\.(\d+)\.(\d+)([A-Za-z0-9.+-]*)")
_PRE = re.compile(r"^[.-]?(a|b|c|rc|alpha|beta|pre|preview|dev)\d*([.-]|$)", re.I)


def parse_version(text):
    """(maj, min, patch, final) ou None; sufixo rc/dev/a/b conta como menor que a final."""
    m = _VER.search(text or "")
    if not m:
        return None
    return int(m[1]), int(m[2]), int(m[3]), 0 if _PRE.match(m[4]) else 1


def find_collector(configured):
    """Mesma ordem do Collector.js: PATH, ~/.local/bin, pipx, caminho configurado."""
    cands = [shutil.which(BIN), os.path.expanduser("~/.local/bin/" + BIN), os.path.expanduser(PIPX),
             os.path.expanduser(configured) if configured else None]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def read_version(path):
    """Executa `<path> --version` sem shell; devolve o texto X.Y.Z ou None se não for confiável."""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, errors="replace",
                           timeout=VERSION_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.fullmatch(BIN + r" (\d+\.\d+\.\d+[A-Za-z0-9.+-]*)", r.stdout.strip())
    return m[1] if r.returncode == 0 and m else None


def python_ok():
    """Há python3 com venv e ensurepip utilizáveis? (só importa; não instala nada)"""
    py = shutil.which("python3")
    if not py:
        return False
    try:
        return subprocess.run([py, "-c", "import venv, ensurepip"], capture_output=True, timeout=VERSION_TIMEOUT,
                              stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def status(required, configured):
    out = {"state": "ausente", "installed": None, "required": required, "path": None, "message": ""}
    req = parse_version(required) if _VER.fullmatch(required) else None
    if req is None:
        out["message"] = "Versão exigida inválida."
        return out
    path = find_collector(configured)
    out["path"] = path
    if path:
        installed = read_version(path)
        inst = parse_version(installed)
        out["installed"] = installed
        if inst is None:
            out["state"] = "desatualizado"
            out["message"] = "Não foi possível ler a versão do Coletor instalado."
        elif inst == req:
            out.update(state="ok", message="Coletor na versão exigida.")
        elif inst > req:
            out.update(state="mais_novo", message="Coletor mais novo que o Plasmoid; nada a fazer.")
        else:
            out.update(state="desatualizado", message="Coletor mais antigo que o exigido pelo Plasmoid.")
    else:
        out["message"] = "Coletor não encontrado."
    if out["state"] in ("ausente", "desatualizado") and not python_ok():
        out.update(state="python_indisponivel", message="Falta python3 com os módulos venv e ensurepip.")
    return out


def main(argv):
    required, configured = "", ""
    try:
        args = argv[1:]
        if not args or args[0] != "status":
            raise ValueError("Subcomando desconhecido.")
        for i, a in enumerate(args):
            if a == "--required" and i + 1 < len(args):
                required = args[i + 1]
            elif a == "--collector-path" and i + 1 < len(args):
                configured = args[i + 1]
        result = status(required, configured)
    except Exception as exc:  # nunca saída vazia nem traceback
        result = {"state": "ausente", "installed": None, "required": required, "path": None,
                  "message": str(exc) if isinstance(exc, ValueError) else "Erro inesperado: %s" % type(exc).__name__}
    print(json.dumps(result))  # ASCII puro: não quebra em stdout não UTF-8
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
