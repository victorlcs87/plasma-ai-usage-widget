"""Caminho de credenciais e API personalizados pela CLI (ticket 38)."""

import io
import json
import os
import stat
from unittest.mock import MagicMock, patch

from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config, save_secure_json

KEY = "sk-secret-gateway-key-123"


def creds(tag):
    return {"claudeAiOauth": {"accessToken": f"at-{tag}", "refreshToken": f"rt-{tag}", "expiresAt": 4102444800000}}


def run(tmp_path, *args, stdin=None):
    argv = [*args, "--config-path", str(tmp_path / "cfg" / "config.json"), "--cache-path", str(tmp_path / "status.json")]
    if stdin is None:
        return main(argv)
    with patch("sys.stdin", io.StringIO(stdin)):
        return main(argv)


def base_cfg(tmp_path, accounts=()):
    cfg = {"version": 1, "agents": {"claude": {"accounts": list(accounts)}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}
    save_config(cfg, tmp_path / "cfg" / "config.json")


def read_cfg(tmp_path):
    return json.loads((tmp_path / "cfg" / "config.json").read_text())


def test_set_provider_config_stores_path_url_and_key_0600(tmp_path, capsys):
    base_cfg(tmp_path)
    alt = tmp_path / "alt-claude"
    code = run(tmp_path, "--set-provider-config", "claude", "--credential-path", str(alt),
               "--api-base-url", "https://gw.example.com/", "--api-key-stdin", stdin=KEY + "\n")
    out = capsys.readouterr()
    assert code == 0
    assert KEY not in out.out + out.err
    claude = read_cfg(tmp_path)["agents"]["claude"]
    assert claude["credential_path"] == str(alt)
    assert claude["api_base_url"] == "https://gw.example.com"
    assert claude["api_key"] == KEY
    assert stat.S_IMODE(os.stat(tmp_path / "cfg" / "config.json").st_mode) == 0o600
    assert KEY not in (tmp_path / "status.json").read_text()


def test_set_provider_config_rejects_insecure_url_and_api_for_other_providers(tmp_path, capsys):
    base_cfg(tmp_path)
    assert run(tmp_path, "--set-provider-config", "claude", "--api-base-url", "http://gw.example.com") == 1
    assert run(tmp_path, "--set-provider-config", "codex", "--api-base-url", "https://gw.example.com") == 1
    assert run(tmp_path, "--set-provider-config", "claude", "--api-base-url", "http://127.0.0.1:8080") == 0
    capsys.readouterr()


def test_empty_values_clear_settings(tmp_path):
    base_cfg(tmp_path)
    run(tmp_path, "--set-provider-config", "claude", "--credential-path", "/x", "--api-base-url", "https://g.io")
    run(tmp_path, "--set-provider-config", "claude", "--credential-path", "", "--api-base-url", "")
    claude = read_cfg(tmp_path)["agents"]["claude"]
    assert "credential_path" not in claude and "api_base_url" not in claude


def test_alternative_path_respected_by_identity_and_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    prof_a = tmp_path / "profiles" / "a" / ".credentials.json"
    prof_b = tmp_path / "profiles" / "b" / ".credentials.json"
    save_secure_json(creds("a"), prof_a)
    save_secure_json(creds("b"), prof_b)
    alt_dir = tmp_path / "alt-claude"
    save_secure_json(creds("a"), alt_dir / ".credentials.json")
    accs = [{"id": "a", "label": "A", "credential_path": str(prof_a)}, {"id": "b", "label": "B", "credential_path": str(prof_b)}]
    base_cfg(tmp_path, accs)
    run(tmp_path, "--set-provider-config", "claude", "--credential-path", str(alt_dir))

    assert run(tmp_path, "--refresh") == 0
    st = json.loads((tmp_path / "status.json").read_text())["agents"]["claude"]["accounts"]
    assert {a["id"]: a["isActive"] for a in st} == {"a": True, "b": False}

    assert run(tmp_path, "--switch-account", "claude", "b") == 0
    applied = json.loads((alt_dir / ".credentials.json").read_text())
    assert applied["claudeAiOauth"]["accessToken"] == "at-b"
    assert not (tmp_path / "_sys_claude" / ".credentials.json").exists()


def _usage_response():
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = json.dumps({"five_hour": {"utilization": 10.0}, "seven_day": {"utilization": 20.0}}).encode()
    resp.__enter__.return_value = resp
    return resp


def test_custom_base_url_queries_gateway_with_configured_key(tmp_path, capsys):
    prof = tmp_path / "profiles" / "a" / ".credentials.json"
    save_secure_json(creds("a"), prof)
    base_cfg(tmp_path, [{"id": "a", "label": "A", "credential_path": str(prof)}])
    run(tmp_path, "--set-provider-config", "claude", "--api-base-url", "https://gw.example.com",
        "--api-key-stdin", stdin=KEY)
    with patch("urllib.request.OpenerDirector.open", return_value=_usage_response()) as op:
        assert run(tmp_path, "--refresh") == 0
    req = op.call_args[0][0]
    assert req.full_url == "https://gw.example.com/api/oauth/usage"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert "at-a" not in str(req.headers)
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err + (tmp_path / "status.json").read_text()


def test_custom_base_url_without_key_never_sends_oauth_token(tmp_path):
    prof = tmp_path / "profiles" / "a" / ".credentials.json"
    save_secure_json(creds("a"), prof)
    base_cfg(tmp_path, [{"id": "a", "label": "A", "credential_path": str(prof)}])
    run(tmp_path, "--set-provider-config", "claude", "--api-base-url", "https://gw.example.com")
    with patch("urllib.request.OpenerDirector.open", return_value=_usage_response()) as op:
        assert run(tmp_path, "--refresh") == 0
    op.assert_not_called()


# --- Correcoes da revisao do ticket 38 ---------------------------------------

import http.server
import threading

import pytest

from ai_usage_collector.config import validate_base_url
from ai_usage_collector.extractors.claude import fetch_claude_usage_api


def _server(handler_cls):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_a1_redirect_is_not_followed_and_token_not_forwarded():
    seen = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    target = _server(Target)

    class Redirector(Target):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/x")
            self.end_headers()

    gw = _server(Redirector)
    try:
        assert fetch_claude_usage_api("tok", base_url=f"http://127.0.0.1:{gw.server_port}") is None
    finally:
        gw.shutdown()
        target.shutdown()
    assert seen == []


@pytest.mark.parametrize("url", [
    "https://user:pw@gw.example.com", "https://gw.example.com?x=1", "https://gw.example.com/#f",
    "https://gw.example.com:99999", "https://gw example.com", "ftp://gw.example.com",
    "http://gw.example.com", "https://gw.example.com?",
])
def test_a2_invalid_urls_rejected_and_extractor_sends_nothing(url):
    with pytest.raises(ValueError):
        validate_base_url(url)
    with patch("urllib.request.OpenerDirector.open") as op:
        assert fetch_claude_usage_api("tok", base_url=url) is None
    op.assert_not_called()


def test_a2_scheme_case_insensitive():
    assert validate_base_url("HTTPS://gw.example.com/") == "HTTPS://gw.example.com"


def test_m1_relative_path_stored_absolute(tmp_path, monkeypatch):
    base_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    run(tmp_path, "--set-provider-config", "claude", "--credential-path", "rel/dir")
    assert read_cfg(tmp_path)["agents"]["claude"]["credential_path"] == str(tmp_path / "rel" / "dir")


def test_m2_override_preserves_final_symlink(tmp_path):
    from ai_usage_collector.config import credential_override
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    base_cfg(tmp_path)
    run(tmp_path, "--set-provider-config", "claude", "--credential-path", str(link))
    assert credential_override("claude", tmp_path / "cfg" / "config.json") == link


def test_m3_gemini_override_skips_keyring_on_switch(tmp_path, monkeypatch):
    for k in ("GEMINI_CREDENTIALS_PATH", "GEMINI_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    prof = tmp_path / "profiles" / "g" / "oauth_creds.json"
    save_secure_json({"access_token": "t", "refresh_token": "r"}, prof)
    cfg = {"version": 1, "agents": {"claude": {"accounts": []}, "codex": {"accounts": []},
           "gemini": {"accounts": [{"id": "g", "label": "G", "credential_path": str(prof)}]}}}
    save_config(cfg, tmp_path / "cfg" / "config.json")
    run(tmp_path, "--set-provider-config", "gemini", "--credential-path", str(tmp_path / "alt-gem"))
    with patch("subprocess.run") as sp:
        run(tmp_path, "--switch-account", "gemini", "g")
    assert not any("secret-tool" in str(c) for c in sp.call_args_list)


def test_m4_empty_stdin_fails_and_clear_flag_removes(tmp_path, capsys):
    base_cfg(tmp_path)
    run(tmp_path, "--set-provider-config", "claude", "--api-base-url", "https://g.io", "--api-key-stdin", stdin=KEY)
    assert run(tmp_path, "--set-provider-config", "claude", "--api-key-stdin", stdin="\n") == 1
    assert read_cfg(tmp_path)["agents"]["claude"]["api_key"] == KEY
    assert run(tmp_path, "--set-provider-config", "claude", "--clear-api-key") == 0
    assert "api_key" not in read_cfg(tmp_path)["agents"]["claude"]
    capsys.readouterr()


def test_b_warnings(tmp_path, capsys):
    base_cfg(tmp_path)
    run(tmp_path, "--set-provider-config", "claude", "--credential-path", str(tmp_path / "nope"), "--api-key-stdin", stdin=KEY)
    out = capsys.readouterr().out
    assert "ainda não existe" in out and "URL base" in out and KEY not in out


def test_migration_with_gemini_override_never_calls_keyring(tmp_path, monkeypatch):
    for k in ("GEMINI_CREDENTIALS_PATH", "GEMINI_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    alt = tmp_path / "alt" / "oauth_creds.json"
    save_secure_json({"access_token": "FILE", "refresh_token": "r"}, alt)
    cfg = {"version": 1, "agents": {"claude": {"accounts": []}, "codex": {"accounts": []},
           "gemini": {"credential_path": str(alt),
                      "accounts": [{"id": "default", "label": "G", "credential_path": str(alt)}]}}}
    save_config(cfg, tmp_path / "cfg" / "config.json")

    with patch("subprocess.run") as sp:
        from ai_usage_collector.config import load_config
        accs = load_config(tmp_path / "cfg" / "config.json")["agents"]["gemini"]["accounts"]
    sp.assert_not_called()  # um chaveiro real traria outro token
    assert json.loads(open(accs[0]["credential_path"]).read())["access_token"] == "FILE"


def test_relative_manual_credential_path_ignored(tmp_path):
    from ai_usage_collector.config import credential_override
    base_cfg(tmp_path)
    c = read_cfg(tmp_path)
    c["agents"]["claude"]["credential_path"] = "rel/dir"
    (tmp_path / "cfg" / "config.json").write_text(json.dumps(c))
    assert credential_override("claude", tmp_path / "cfg" / "config.json") is None
