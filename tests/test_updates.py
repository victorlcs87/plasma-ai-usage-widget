"""Verificacao de atualizacao (ticket 39) pela CLI, com opener e versoes locais simulados (nenhuma rede real)."""

import json
import stat
import urllib.error

import pytest

from ai_usage_collector import updates
from ai_usage_collector.cli import main
from ai_usage_collector.contract import CONTRACT_VERSION, validate_status_contract
from test_pace import env  # noqa: F401  (fixture)

W, C, X, G = (updates.SOURCES[k][0] for k in ("widget", "claude", "codex", "gemini"))
GOOD_URL = "https://github.com/victorlcs87/plasma-ai-usage-widget/releases/tag/v9.0.0"


class Resp:
    status = 200

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

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
    return opener


def items(env):  # noqa: F811
    return json.loads(env.cache_path.read_text())["updates"]["items"]


def test_uses_the_no_redirect_opener():
    from ai_usage_collector.extractors.claude import _NO_REDIRECT

    assert updates._OPENER is _NO_REDIRECT


def test_available_updates_compare_with_local_versions(env, net):  # noqa: F811
    env()
    got = items(env)
    assert got["widget"] == {"latest": "9.0.0", "current": "0.1.0", "available": True, "url": GOOD_URL}
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
                "https://github.com/outro/repo/releases/v9", GOOD_URL + " x", GOOD_URL + "\n<b>", 5, None):
        net.routes[W] = {"tag_name": "v9.0.0", "html_url": bad}
        env.state.update(calls=0)
        env.cache_path.with_name(updates.STATE_FILENAME).unlink(missing_ok=True)
        env()
        assert items(env)["widget"] == {"latest": "9.0.0", "current": "0.1.0", "available": True}, bad


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


def test_cli_is_only_run_while_an_update_is_pending(env, net):  # noqa: F811
    env()
    assert net.local_calls == ["claude", "codex", "gemini"]
    env(minutes=5)
    assert net.local_calls.count("claude") == 2 and net.local_calls.count("gemini") == 1  # claude ainda pendente
    net.local["claude"] = "2.1.0"
    env(minutes=10)
    assert items(env)["claude"]["available"] is False  # atualizou: o selo some sem esperar o dia
    n = len(net.local_calls)
    env(minutes=15)
    assert len(net.local_calls) == n


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
