#!/usr/bin/env python3
"""Instalador do Coletor (empacotado no Plasmoid). Só stdlib; roda com o python3 do sistema, sem o Coletor.

Uso: collector-installer.py status --required X.Y.Z [--collector-path CAMINHO]
Imprime sempre UMA linha de JSON e sai com 0:
  {"state": ausente|desatualizado|ok|mais_novo|python_indisponivel,
   "installed": "X.Y.Z"|null, "required": "X.Y.Z", "path": str|null, "message": str}

Uso: collector-installer.py install --version X.Y.Z
Instala plasma-ai-usage-collector==X.Y.Z no venv do widget (~/.local/share/plasma-ai-usage/venv) e liga
~/.local/bin/ai-usage-collector a ele. Sem privilegios elevados e sem shell. O indice vem so do ambiente (PIP_INDEX_URL,
PIP_FIND_LINKS, PIP_NO_INDEX...), nunca de argumento. Saida: uma linha JSON por evento (flush a cada linha):
  {"step": venv|download|install|link|verify, "status": start|ok|error, "message": str}
e a ultima: {"result": ok|error, "cause": null|python_indisponivel|rede|versao_inexistente|permissao|
  conflito_em_local_bin|verificacao|falha, "message": str, "log": [ultimas ~30 linhas do pip]}.
Exit 0 so em sucesso. Escreve apenas no venv do widget, nos symlinks e no lock (install.lock ao lado do venv).
"""
import collections
import errno
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading

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


PACKAGE = "plasma-ai-usage-collector"
LINKS = (BIN, "ai-usage-session-state")
PIP_TIMEOUT = 300
VENV_TIMEOUT = 120
_STRICT = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# variáveis que redirecionariam onde o pip escreve (o índice, ao contrário, vem do ambiente)
_DROP_ENV = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PIP_USER",
             "PIP_PYTHON", "PIP_CACHE_DIR")
_NOPERM = (errno.EACCES, errno.EPERM, errno.EROFS)


class _Fail(Exception):
    def __init__(self, cause, message, step=None, log=()):
        super().__init__(message)
        self.cause, self.step, self.log = cause, step, list(log)


class _Interrupted(Exception):
    pass


def _emit(obj):
    print(json.dumps(obj), flush=True)


def _step(step, status, message=""):
    _emit({"step": step, "status": status, "message": message})


def _scrub(line, home):
    """Tira credenciais de URL e troca o HOME por ~ no log."""
    line = re.sub(r"://[^/\s]*@", "://***@", line.rstrip())
    return line.replace(home, "~") if len(home) > 1 else line


def _link_state(dest, venv):
    """'novo' (não existe) ou 'nosso' (symlink para dentro do venv do widget); senão levanta conflito."""
    if not os.path.lexists(dest):
        return "novo"
    if os.path.islink(dest):
        tgt = os.path.abspath(os.path.join(os.path.dirname(dest), os.readlink(dest)))
        if tgt.startswith(venv + os.sep):
            return "nosso"
    raise _Fail("conflito_em_local_bin", "%s já existe e não é do widget (você já tem outro coletor). "
                "Nada foi alterado." % dest.replace(os.path.expanduser("~"), "~", 1), "link")


def _killpg(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def _run_pip(cmd, env, home, log):
    """Roda o pip lendo a saída linha a linha (progresso download -> install); mata o grupo no timeout/sinal."""
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", env=env, start_new_session=True)
    timed_out, done = [], []

    def kill():
        if not done:  # pip já terminou: não mata (pgid pode ser reaproveitado)
            timed_out.append(1)
            _killpg(proc)

    timer = threading.Timer(PIP_TIMEOUT, kill)
    timer.start()
    installing = False
    try:
        _step("download", "start", "Baixando %s." % PACKAGE)
        for line in proc.stdout:
            log.append(_scrub(line, home))
            if not installing and line.startswith("Installing collected packages"):
                installing = True
                _step("download", "ok")
                _step("install", "start", "Instalando.")
        done.append(1)
        proc.wait()
    except BaseException:
        done.append(1)
        _killpg(proc)
        proc.wait()
        raise
    finally:
        timer.cancel()
    return proc.returncode, installing, bool(timed_out)


def _classify(text):
    if re.search(r"PermissionError|EACCES|Permission denied", text):
        return "permissao"
    if re.search(r"Could not fetch URL|Connection|Temporary failure|Name or service not known|Max retries", text):
        return "rede"
    if re.search(r"No matching distribution|Could not find a version", text):
        return "versao_inexistente"
    return "falha"


def _prepare_venv(venv, base, env, created, home):
    vbin = os.path.join(venv, "bin")
    if os.access(os.path.join(vbin, "python"), os.X_OK) and os.access(os.path.join(vbin, "pip"), os.X_OK):
        return  # venv íntegro: reutiliza (e nunca apaga)
    if os.path.lexists(venv):
        vazio_ou_venv = os.path.isdir(venv) and not os.path.islink(venv) and (
            os.path.isfile(os.path.join(venv, "pyvenv.cfg")) or not os.listdir(venv))
        if not vazio_ou_venv:
            raise _Fail("falha", "O destino do venv existe e não parece um venv do widget.", "venv")
    py = shutil.which("python3")
    ok = py and subprocess.run([py, "-c", "import venv, ensurepip"], capture_output=True, env=env,
                               timeout=VERSION_TIMEOUT, stdin=subprocess.DEVNULL).returncode == 0
    if not ok:
        raise _Fail("python_indisponivel", "Falta python3 com venv e ensurepip. Instale o pacote do sistema "
                    "(ex.: python3-venv no Debian/Ubuntu) e tente de novo.", "venv")
    shutil.rmtree(venv, ignore_errors=True)  # resto de tentativa interrompida (sem pip)
    os.makedirs(base, exist_ok=True)
    created["venv"] = venv
    r = subprocess.run([py, "-m", "venv", venv], capture_output=True, text=True, errors="replace", env=env,
                       timeout=VENV_TIMEOUT, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        text = r.stdout + r.stderr
        cause = "permissao" if _classify(text) == "permissao" else "python_indisponivel"
        raise _Fail(cause, "Não foi possível criar o venv do widget.", "venv",
                    [_scrub(x, home) for x in text.splitlines()[-30:]])


def _do_install(version, home, created):
    base = os.path.join(home, ".local", "share", "plasma-ai-usage")
    venv = os.path.join(base, "venv")
    binds = os.path.join(home, ".local", "bin")
    vbin = os.path.join(venv, "bin")
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    log = collections.deque(maxlen=2000)
    try:
        _link_state(os.path.join(binds, BIN), venv)  # conflito primeiro: falha cedo, sem efeito colateral

        _step("venv", "start", "Preparando o ambiente do widget.")
        _prepare_venv(venv, base, env, created, home)
        _step("venv", "ok", "Ambiente pronto.")

        cmd = [os.path.join(vbin, "pip"), "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir",
               "%s==%s" % (PACKAGE, version)]
        code, installing, timed_out = _run_pip(cmd, env, home, log)
        if code != 0 or timed_out:
            cause = "rede" if timed_out else _classify("\n".join(log))
            raise _Fail(cause, "Tempo esgotado ao instalar." if timed_out else "O pip falhou (%s)." % cause,
                        "install" if installing else "download")
        if not installing:  # pip sem a linha de progresso (já satisfeito)
            _step("download", "ok")
            _step("install", "start", "Instalando.")
        _step("install", "ok", "Coletor %s instalado." % version)

        _step("link", "start", "Criando atalhos em ~/.local/bin.")
        os.makedirs(binds, exist_ok=True)
        for name in LINKS:
            target, dest = os.path.join(vbin, name), os.path.join(binds, name)
            if not os.path.exists(target):
                if name == BIN:
                    raise _Fail("verificacao", "O executável do Coletor não foi instalado.", "link")
                continue
            if _link_state(dest, venv) == "novo":
                try:
                    os.symlink(target, dest)  # atômico: nunca sobrescreve o que surgiu depois da checagem
                except FileExistsError:
                    raise _Fail("conflito_em_local_bin", "%s foi criado por outro programa; nada foi alterado."
                                % dest.replace(home, "~", 1), "link")
                created.setdefault("links", []).append(dest)
            else:  # nosso symlink (versão/venv antigos): troca atômica
                tmp = "%s.tmp-%d" % (dest, os.getpid())
                try:
                    os.symlink(target, tmp)
                    os.replace(tmp, dest)
                finally:
                    if os.path.islink(tmp):
                        os.unlink(tmp)
        _step("link", "ok", "Atalhos prontos.")

        _step("verify", "start", "Verificando o Coletor.")
        got = read_version(os.path.join(vbin, BIN))
        if got != version:
            raise _Fail("verificacao", "O Coletor instalado reporta a versão %s, não %s." % (got, version), "verify")
        _step("verify", "ok", "ai-usage-collector %s." % got)
    except subprocess.TimeoutExpired:
        raise _Fail("falha", "Tempo esgotado.", log=list(log)[-30:])
    except _Fail as f:
        f.log = f.log or list(log)[-30:]
        raise
    except OSError as exc:
        raise _Fail("permissao" if exc.errno in _NOPERM else "falha",
                    "Erro de sistema: %s." % (exc.strerror or type(exc).__name__))


def install(version):
    home = os.path.expanduser("~")
    lockdir = os.path.join(home, ".local", "share", "plasma-ai-usage")
    created = {}
    try:
        os.makedirs(lockdir, exist_ok=True)
        lock = os.open(os.path.join(lockdir, "install.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as exc:
        return {"result": "error", "cause": "permissao" if exc.errno in _NOPERM else "falha",
                "message": "Erro de sistema: %s." % exc.strerror, "log": []}
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # o SO solta se o processo morrer: nunca trava a próxima
    except OSError:
        os.close(lock)
        return {"result": "error", "cause": "falha", "message": "Já há uma instalação em andamento.", "log": []}

    def on_signal(signum, frame):
        raise _Interrupted()

    old = {s: signal.signal(s, on_signal) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    result = {"result": "ok", "cause": None, "message": "Coletor %s instalado." % version, "log": []}
    try:
        _do_install(version, home, created)
    except (_Fail, _Interrupted) as exc:
        fail = exc if isinstance(exc, _Fail) else _Fail("falha", "Instalação interrompida.")
        for sg in old:  # a limpeza não pode ser abortada por um segundo sinal
            signal.signal(sg, signal.SIG_IGN)
        _cleanup(created)
        if fail.step:
            _step(fail.step, "error", str(fail))
        result = {"result": "error", "cause": fail.cause, "message": str(fail), "log": fail.log}
    except Exception as exc:  # nunca sem resultado final
        _cleanup(created)
        result = {"result": "error", "cause": "falha", "message": "Erro inesperado: %s." % type(exc).__name__,
                  "log": []}
    finally:
        for s, h in old.items():
            signal.signal(s, h)
        os.close(lock)
    return result


def _cleanup(created):
    """Remove só o que ESTE install criou de novo (symlinks novos e venv recém-criado)."""
    for dest in created.get("links", []):
        try:
            if os.path.islink(dest):
                os.unlink(dest)
        except OSError:
            pass
    if "venv" in created:
        shutil.rmtree(created["venv"], ignore_errors=True)


def main_install(args):
    if len(args) != 3 or args[1] != "--version" or not _STRICT.fullmatch(args[2]):
        res = {"result": "error", "cause": "falha", "log": [],
               "message": "Uso: install --version X.Y.Z (versão exata, sem outros argumentos)."}
    else:
        res = install(args[2])
    _emit(res)
    return 0 if res["result"] == "ok" else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "install":
        return main_install(argv[1:])
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
