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
    with patch("urllib.request.urlopen", return_value=_usage_response()) as op:
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
    with patch("urllib.request.urlopen", return_value=_usage_response()) as op:
        assert run(tmp_path, "--refresh") == 0
    op.assert_not_called()
