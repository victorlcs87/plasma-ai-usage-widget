"""Verificacao de atualizacao (ticket 39) pela CLI, com opener e versoes locais simulados (nenhuma rede real)."""

import json
import stat
import urllib.error

import pytest

from ai_usage_collector import __version__, refresh, updates
from ai_usage_collector.cli import main
from ai_usage_collector.contract import CONTRACT_VERSION, validate_status_contract
from test_pace import env  # noqa: F401  (fixture)

W, C, X, G = (updates.SOURCES[k][0] for k in ("widget", "claude", "codex", "gemini"))
GOOD_URL = "https://github.com/victorlcs87/plasma-ai-usage-widget/releases/tag/v9.0.0"


class Resp:
    status = 200

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.pos = 0

    def read(self, n=-1):
        end = len(self.body) if n < 0 else self.pos + n
        chunk, self.pos = self.body[self.pos:end], min(end, len(self.body))
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self):
        self.calls = []
        self.routes = {
            W: {"tag_name": "v9.0.0", "html_url": GOOD_URL},
            C: {"name": "@anthropic-ai/claude-code", "version": "2.1.0"},
            X: {"name": "@openai/codex", "version": "0.9.0"},
            G: {"name": "@google/gemini-cli", "version": "0.5.0"},
        }

    def open(self, request, timeout=None):
        self.calls.append(request)
        route = self.routes.get(request.full_url)
        if isinstance(route, Exception):
            raise route
        if route is None:
            raise urllib.error.URLError("sem rota")
        return route if isinstance(route, Resp) else Resp(route)


@pytest.fixture
def net(env, monkeypatch):  # noqa: F811
    opener = FakeOpener()
    opener.local = {"claude": "2.0.0", "codex": None, "gemini": "0.9.0"}
    opener.local_calls = []
    monkeypatch.setattr(updates, "_OPENER", opener)

    def local(binary):
        opener.local_calls.append(binary)
        return opener.local[binary]

    monkeypatch.setattr(updates, "local_version", local)
    opener.sig = {b: [f"/bin/{b}", 1, 1] for b in ("claude", "codex", "gemini")}
    monkeypatch.setattr(updates, "_signature", lambda b: opener.sig[b])
    return opener


def items(env):  # noqa: F811
    return json.loads(env.cache_path.read_text())["updates"]["items"]


def test_uses_the_no_redirect_opener():
    from ai_usage_collector.extractors import claude

    assert updates._OPENER is refresh.NO_REDIRECT_OPENER
    assert not hasattr(claude, "_NO_REDIRECT")


def test_available_updates_compare_with_local_versions(env, net):  # noqa: F811
    env()
    got = items(env)
    assert got["widget"] == {"latest": "9.0.0", "current": __version__, "available": True, "url": GOOD_URL}
    assert got["claude"] == {"latest": "2.1.0", "current": "2.0.0", "available": True}
    assert got["codex"] == {"latest": "0.9.0", "current": None, "available": False}  # local desconhecida
    assert got["gemini"] == {"latest": "0.5.0", "current": "0.9.0", "available": False}  # local mais nova


def test_queries_each_source_once_per_day(env, net):  # noqa: F811
    env(minutes=0)
    assert sorted(r.full_url for r in net.calls) == sorted([W, C, X, G])
    env(minutes=5)
    env(minutes=23 * 60)
    assert len(net.calls) == 4
    env(minutes=24 * 60 + 1)
    assert len(net.calls) == 8
    assert items(env)["claude"]["latest"] == "2.1.0"  # entre consultas o resultado vem do cache


def test_request_is_anonymous_https_and_fixed(env, net):  # noqa: F811
    env()
    for req in net.calls:
        assert req.full_url.startswith(("https://api.github.com/", "https://registry.npmjs.org/"))
        assert {k.lower() for k, _ in req.header_items()} <= {"accept", "user-agent"}


def test_disabled_never_queries_and_can_be_enabled_again(env, net):  # noqa: F811
    assert main(["--set-update-config", "--update-check", "off", *env.base]) == 0
    env()
    env(minutes=48 * 60)
    status = json.loads(env.cache_path.read_text())
    assert net.calls == [] and net.local_calls == []
    assert status["updates"] == {"enabled": False, "items": {}}
    assert not env.cache_path.with_name(updates.STATE_FILENAME).exists()
    assert main(["--set-update-config", "--update-check", "on", *env.base]) == 0
    assert json.loads(env.cache_path.read_text())["updates"]["enabled"] is True
    assert net.calls == []  # reaplicar a configuracao nao consulta a rede
    env(minutes=48 * 60 + 1)
    assert len(net.calls) == 4


def test_update_config_requires_a_value(env, net, capsys):  # noqa: F811
    assert main(["--set-update-config", *env.base]) == 1
    assert "--update-check" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("sem rede"),
    urllib.error.HTTPError("u", 500, "erro", {}, None),
    urllib.error.HTTPError("u", 302, "redirect", {}, None),  # o opener sem redirect levanta 3xx
    urllib.error.HTTPError("u", 403, "rate limit", {}, None),
    TimeoutError(),
    Resp(b"<html>not json"),
    Resp(b"[1, 2]"),
    Resp(b'{"tag_name": '),
])
def test_network_failure_is_silent_and_consumes_the_day(env, net, capsys, failure):  # noqa: F811
    net.routes = {u: failure for u in (W, C, X, G)}
    acc = env()
    assert acc["health"]["status"] == "valid"
    assert capsys.readouterr().err == ""
    assert items(env) == {}
    env(minutes=60)
    assert len(net.calls) == 4  # sem rajada: a falha tambem conta como a consulta do dia


def test_failure_keeps_last_known_version(env, net):  # noqa: F811
    env()
    net.routes = {u: urllib.error.URLError("x") for u in (W, C, X, G)}
    env(minutes=25 * 60)
    assert len(net.calls) == 8
    assert items(env)["claude"]["latest"] == "2.1.0"


@pytest.mark.parametrize("tag", ["garbage", "1.2", "", 123, None, "1.2.3.4", "v1.2.3 && rm -rf", "9" * 40 + ".0.0", ["1.0.0"]])
def test_strange_versions_are_ignored(env, net, tag):  # noqa: F811
    net.routes[C] = {"name": "@anthropic-ai/claude-code", "version": tag}
    env()
    assert "claude" not in items(env)
    assert "widget" in items(env)


def test_prerelease_and_v_prefix_comparison(env, net):  # noqa: F811
    net.routes[W] = {"tag_name": "v2.0.0-beta.2", "html_url": GOOD_URL}
    net.routes[C] = {"name": "@anthropic-ai/claude-code", "version": "2.0.0"}
    net.local["claude"] = "2.0.0-rc.1"
    env()
    got = items(env)
    assert got["widget"]["latest"] == "2.0.0-beta.2" and got["widget"]["available"] is True  # 0.1.0 < 2.0.0-beta.2
    assert got["claude"]["available"] is True  # 2.0.0-rc.1 < 2.0.0


@pytest.mark.parametrize("latest,current,newer", [
    ("1.0.0", "1.0.0-rc.1", True), ("1.0.0-rc.1", "1.0.0", False), ("1.0.0-rc.2", "1.0.0-rc.10", False),
    ("1.0.0-rc.10", "1.0.0-rc.2", True), ("1.0.0-alpha", "1.0.0-1", True), ("v1.10.0", "1.9.9", True),
    ("1.0.0+build5", "1.0.0", False), ("1.0.0", "nope", False), ("nope", "1.0.0", False), (None, None, False),
])
def test_version_ordering(latest, current, newer):
    assert updates.is_newer(latest, current) is newer


def test_huge_response_is_rejected(env, net):  # noqa: F811
    net.routes[C] = Resp(b"{" + b" " * (10 * 1024 * 1024) + b'"version": "9.0.0"}')
    env()
    assert "claude" not in items(env)


def test_unexpected_release_url_is_not_exposed(env, net):  # noqa: F811
    for bad in ("https://evil.example/releases/v9", "http://github.com/victorlcs87/plasma-ai-usage-widget/x",
                "https://github.com/victorlcs87/plasma-ai-usage-widget.evil.com/x", "javascript:alert(1)",
                "https://github.com/outro/repo/releases/v9", GOOD_URL + "../../x",
                GOOD_URL + "/%2e%2e/x", GOOD_URL + "/..%2fx", GOOD_URL + "%2Fx", GOOD_URL + "%5cx",
                "https://github.com/victorlcs87/plasma-ai-usage-widget/tree/main", GOOD_URL + "%zz", GOOD_URL + "100%", GOOD_URL + " x", GOOD_URL + "\n<b>", 5, None):
        net.routes[W] = {"tag_name": "v9.0.0", "html_url": bad}
        env.state.update(calls=0)
        env.cache_path.with_name(updates.STATE_FILENAME).unlink(missing_ok=True)
        env()
        assert items(env)["widget"] == {"latest": "9.0.0", "current": __version__, "available": True}, bad


def test_wrong_package_name_is_ignored(env, net):  # noqa: F811
    net.routes[X] = {"name": "evil-package", "version": "9.9.9"}
    env()
    assert "codex" not in items(env)


def test_backwards_clock_does_not_burst_and_recovers(env, net):  # noqa: F811
    env(minutes=0)
    env(minutes=-3 * 24 * 60)
    env(minutes=-2 * 24 * 60)
    assert len(net.calls) == 4
    env(minutes=60)
    assert len(net.calls) == 4
    env(minutes=25 * 60)
    assert len(net.calls) == 8


@pytest.mark.parametrize("junk", [
    "not json", "[]", '{"sources": 5}', '{"sources": {"claude": 7}}',
    json.dumps({"sources": {s: {"checked_at": "ontem", "latest": 5, "url": "https://evil.example/", "local": ["x"]}
                            for s in updates.SOURCES}}),
    json.dumps({"sources": {s: {"checked_at": 1e999, "latest": "<script>", "local": "9" * 300} for s in updates.SOURCES}}),
])
def test_corrupt_state_is_tolerated_and_rewritten_0600(env, net, junk):  # noqa: F811
    path = env.cache_path.with_name(updates.STATE_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(junk)
    env()
    assert len(net.calls) == 4 and items(env)["claude"]["latest"] == "2.1.0"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    saved = json.loads(path.read_text())["sources"]
    assert saved["widget"]["url"] == GOOD_URL and "evil" not in path.read_text()


def test_version_is_only_rerun_when_the_binary_changes(env, net):  # noqa: F811
    env()
    assert net.local_calls == ["claude", "codex", "gemini"]
    env(minutes=5)
    env(minutes=10)
    assert len(net.local_calls) == 3  # atualizacao pendente, mas o binario nao mudou: nada e executado
    net.local["claude"] = "2.1.0"
    net.sig["claude"] = ["/bin/claude", 2, 1]  # o CLI foi atualizado
    env(minutes=15)
    assert net.local_calls[3:] == ["claude"] and items(env)["claude"]["available"] is False  # selo some sem esperar o dia
    env(minutes=20)
    assert len(net.local_calls) == 4


def test_lock_is_free_while_the_network_runs(env, net):  # noqa: F811
    import fcntl

    lock_path = env.cache_path.with_name("refresh_state.lock")
    free = []
    real_open = net.open

    def open_checking_lock(request, timeout=None):
        with open(lock_path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                free.append(True)
            except BlockingIOError:
                free.append(False)
        return real_open(request, timeout)

    net.open = open_checking_lock
    env()
    assert free == [True] * 4 and items(env)["claude"]["latest"] == "2.1.0"


def test_slow_server_respects_the_total_budget(env, net, monkeypatch):  # noqa: F811
    import http.client
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(1)
            except OSError:
                pass

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class LocalOpener:
        def open(self, request, timeout=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)
            conn.request("GET", "/")
            return conn.getresponse()

    monkeypatch.setattr(updates, "_OPENER", LocalOpener())
    monkeypatch.setattr(updates, "NETWORK_BUDGET", 1.0)
    try:
        start = time.monotonic()
        env()
        elapsed = time.monotonic() - start
    finally:
        server.shutdown()
    assert elapsed < 2.5, elapsed  # 4 fontes a 1 byte/s: orcamento TOTAL, nao por fonte
    assert items(env) == {}


def test_hanging_dns_or_connect_is_abandoned_at_the_budget(env, net, monkeypatch):  # noqa: F811
    import threading
    import time

    release = threading.Event()

    class Hang:
        def open(self, request, timeout=None):
            release.wait(10)
            raise OSError("preso")

    monkeypatch.setattr(updates, "_OPENER", Hang())
    monkeypatch.setattr(updates, "NETWORK_BUDGET", 0.5)
    start = time.monotonic()
    env()
    release.set()
    assert time.monotonic() - start < 2.5 and items(env) == {}


def test_contract_stays_v5_and_validates_updates(env, net):  # noqa: F811
    env()
    status = json.loads(env.cache_path.read_text())
    assert status["version"] == CONTRACT_VERSION == 5 and validate_status_contract(status)
    for bad in ({"enabled": "sim", "items": {}}, {"enabled": True, "items": []},
                {"enabled": True, "items": {"claude": {"latest": 1, "available": True}}},
                {"enabled": True, "items": {"claude": {"latest": "1.0.0", "available": "sim"}}}, []):
        assert not validate_status_contract({**status, "updates": bad})
    assert validate_status_contract({k: v for k, v in status.items() if k != "updates"})


def test_local_version_runs_binary_with_args_list_and_timeout(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "claude": "echo '2.1.5 (Claude Code)'",
        "codex": "sleep 5",
        "gemini": "echo 'erro' >&2; exit 1",
    }
    for name, body in scripts.items():
        f = bin_dir / name
        f.write_text(f"#!/bin/sh\n[ \"$1\" = \"--version\" ] || exit 9\n{body}\n")
        f.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(updates, "VERSION_TIMEOUT", 0.3)
    assert updates.local_version("claude") == "2.1.5"
    assert updates.local_version("codex") is None  # timeout
    assert updates.local_version("gemini") is None  # falhou
    assert updates.local_version("inexistente") is None
    monkeypatch.setenv("PATH", "relativo")
    assert updates.local_version("claude") is None


def test_local_version_caps_output_and_kills_the_whole_group(tmp_path, monkeypatch):
    import os
    import time

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pidfile = tmp_path / "pid"
    scripts = {
        "claude": "yes AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # despeja sem parar
        "codex": f"sleep 30 &\necho $! > {pidfile}\nsleep 30",  # neto sobrevive ao timeout do filho
        "gemini": f"sleep 30 &\necho $! > {pidfile}\necho 0.7.1",  # neto sobrevive a saida normal
    }
    for name, body in scripts.items():
        f = bin_dir / name
        f.write_text(f"#!/bin/sh\n{body}\n")
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(updates, "VERSION_TIMEOUT", 0.5)

    def gone(pid):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.05)
        return False

    start = time.monotonic()
    assert updates.local_version("claude") is None
    assert time.monotonic() - start < 2
    assert updates.local_version("codex") is None
    assert gone(int(pidfile.read_text()))
    assert updates.local_version("gemini") == "0.7.1"
    assert gone(int(pidfile.read_text()))


def test_semver_is_ascii_only():
    assert updates.parse_version("1.2.3") and not updates.parse_version("\u0661.\u0662.\u0663")


def test_version_is_found_on_any_output_line(tmp_path, monkeypatch):
    f = tmp_path / "bin" / "claude"
    f.parent.mkdir()
    f.write_text("#!/bin/sh\necho 'Welcome to the tool'\necho 'tool 2.3.4-rc.1 (build)'\n")
    f.chmod(0o755)
    monkeypatch.setenv("PATH", str(f.parent))
    assert updates.local_version("claude") == "2.3.4-rc.1"


def test_vanished_binary_keeps_known_version_until_the_daily_check(env, net):  # noqa: F811
    env()
    net.sig["claude"], net.local["claude"] = None, None  # nao achado no PATH deste ciclo
    env(minutes=5)
    assert items(env)["claude"]["current"] == "2.0.0"
    env(minutes=25 * 60)
    assert items(env)["claude"]["current"] is None


def test_enabled_follows_the_config_even_if_turned_off_during_the_query(env, net):  # noqa: F811
    real_open, done = net.open, []

    def open_then_disable(request, timeout=None):
        if not done:
            done.append(main(["--set-update-config", "--update-check", "off", *env.base]))
        return real_open(request, timeout)

    net.open = open_then_disable
    env()
    assert done == [0]
    assert json.loads(env.cache_path.read_text())["updates"] == {"enabled": False, "items": {}}


def check(env, capsys):  # noqa: F811
    capsys.readouterr()
    assert main(["--check-update", *env.base]) == 0
    return json.loads(capsys.readouterr().out)


def test_forced_check_ignores_daily_interval_only_for_widget(env, net, capsys):  # noqa: F811
    env()
    net.calls.clear()
    net.routes[W] = {"tag_name": "v9.1.0", "html_url": GOOD_URL}
    out = check(env, capsys)  # mesmo dia: o intervalo diario seria respeitado
    assert out == {"update": "nova", "version": "9.1.0", "url": GOOD_URL}
    assert [r.full_url for r in net.calls] == [W]  # uma consulta, nada de npm
    assert items(env)["widget"]["latest"] == "9.1.0"  # estado que o Plasmoid le
    saved = json.loads(env.cache_path.with_name(updates.STATE_FILENAME).read_text())
    assert saved["sources"]["claude"]["latest"] == "2.1.0"


def test_forced_check_current_version(env, net, capsys):  # noqa: F811
    env()
    net.routes[W] = {"tag_name": f"v{__version__}", "html_url": GOOD_URL}
    assert check(env, capsys) == {"update": "atual", "version": __version__}
    assert items(env)["widget"]["available"] is False


def test_forced_check_network_failure_is_silent_and_keeps_last_version(env, net, capsys):  # noqa: F811
    env()
    net.routes[W] = urllib.error.URLError("sem rede")
    net.calls.clear()
    assert check(env, capsys) == {"update": "indisponivel"}
    assert len(net.calls) == 1
    assert items(env)["widget"]["latest"] == "9.0.0"


def test_forced_check_disabled_does_not_query(env, net, capsys):  # noqa: F811
    assert main(["--set-update-config", "--update-check", "off", *env.base]) == 0
    assert check(env, capsys) == {"update": "indisponivel"}
    assert net.calls == []
