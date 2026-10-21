"""Tests for CLI --add-account functionality."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
import pytest

from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config, save_config, generate_account_slug


def run_cli(*args):
    cmd = [sys.executable, "-m", "ai_usage_collector.cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_slug_generation_sanitization():
    assert generate_account_slug("Claude Trabalho") == "claude-trabalho"
    assert generate_account_slug("Codex @ Dev #1!") == "codex-dev-1"
    assert generate_account_slug("Ação & Reação 2026") == "acao-reacao-2026"
    assert generate_account_slug("!!!") == "account"

    # Collision resolution
    existing = {"claude-dev", "claude-dev-2"}
    assert generate_account_slug("Claude Dev", existing) == "claude-dev-3"


def test_cli_add_account_claude_success(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    cred_dir = tmp_path / ".claude"
    cred_dir.mkdir()
    cred_file = cred_dir / ".credentials.json"
    cred_file.write_text(json.dumps({
        "claudeAiOauth": {"accessToken": "sk-test", "subscriptionType": "pro"}
    }))

    code = main([
        "--add-account",
        "--provider", "claude",
        "--label", "Claude - Trabalho 2026",
        "--credential-path", str(cred_file),
        "--invite-url", "https://claude.ai/invite/work",
        "--total-capacity", "90",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "adicionada com sucesso ao provedor 'claude'" in captured.out
    assert captured.err == ""

    # Verify config persistence
    cfg = load_config(config_path)
    claude_accs = cfg["agents"]["claude"]["accounts"]
    assert len(claude_accs) >= 1
    new_acc = next(a for a in claude_accs if a["id"] == "claude-trabalho-2026")
    assert new_acc["name"] == "Claude - Trabalho 2026"
    assert new_acc["label"] == "Claude - Trabalho 2026"
    assert new_acc["credential_path"] == str(cred_file)
    assert new_acc["manual_invite_url"] == "https://claude.ai/invite/work"
    assert new_acc["rate_limit_capacity"] == 90
    assert new_acc["source"] == "manual"

    # Verify permissions 0600 on config
    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert mode == 0o600

    # Verify status.json cache was created/updated
    assert cache_path.exists()
    cache = json.load(open(cache_path))
    cache_accs = cache["agents"]["claude"]["accounts"]
    assert any(a["id"] == "claude-trabalho-2026" for a in cache_accs)


def test_cli_add_account_codex_with_aliases(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    codex_dir = tmp_path / ".codex-secondary"
    codex_dir.mkdir()
    auth_file = codex_dir / "auth.json"
    auth_file.write_text(json.dumps({"tokens": {"access_token": "token-xyz"}}))

    # Use aliases --name and --dir
    code = main([
        "--add-account",
        "--provider", "codex",
        "--name", "Codex Secundário",
        "--dir", str(codex_dir),
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "adicionada com sucesso ao provedor 'codex'" in captured.out

    cfg = load_config(config_path)
    codex_accs = cfg["agents"]["codex"]["accounts"]
    new_acc = next(a for a in codex_accs if a["id"] == "codex-secundario")
    assert new_acc["name"] == "Codex Secundário"
    assert new_acc["codex_dir"] == str(codex_dir)


def test_cli_add_account_gemini(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    gemini_file = tmp_path / "oauth_creds.json"
    gemini_file.write_text(json.dumps({"access_token": "ya29.test"}))

    code = main([
        "--add-account",
        "--provider", "gemini",
        "--label", "Gemini Pro",
        "--credential-path", str(gemini_file),
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "adicionada com sucesso ao provedor 'gemini'" in captured.out

    cfg = load_config(config_path)
    gemini_accs = cfg["agents"]["gemini"]["accounts"]
    new_acc = next(a for a in gemini_accs if a["id"] == "gemini-pro")
    assert new_acc["name"] == "Gemini Pro"


def test_cli_add_account_with_status_flag(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    cred_file = tmp_path / ".credentials.json"
    cred_file.write_text(json.dumps({"accessToken": "tok"}))

    code = main([
        "--add-account",
        "--provider", "claude",
        "--label", "Claude Test",
        "--credential-path", str(cred_file),
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "adicionada com sucesso" in captured.out
    json_start = captured.out.find("{")
    assert json_start != -1
    parsed_json = json.loads(captured.out[json_start:])
    assert parsed_json["version"] == 4
    assert any(a["id"] == "claude-test" for a in parsed_json["agents"]["claude"]["accounts"])


def test_cli_add_account_validation_errors(capsys, tmp_path):
    config_path = tmp_path / "config.json"

    # Missing provider
    res_no_prov = main([
        "--add-account",
        "--label", "Test",
        "--credential-path", "/some/path",
        "--config-path", str(config_path),
    ])
    assert res_no_prov == 1
    err = capsys.readouterr().err
    assert "Parâmetro --provider é obrigatório" in err

    # Invalid provider
    res_inv_prov = main([
        "--add-account",
        "--provider", "invalid_provider",
        "--label", "Test",
        "--credential-path", "/some/path",
        "--config-path", str(config_path),
    ])
    assert res_inv_prov == 1
    err = capsys.readouterr().err
    assert "Provedor inválido 'invalid_provider'" in err

    # Missing label
    res_no_label = main([
        "--add-account",
        "--provider", "claude",
        "--credential-path", "/some/path",
        "--config-path", str(config_path),
    ])
    assert res_no_label == 1
    err = capsys.readouterr().err
    assert "Parâmetro --label / --name é obrigatório" in err

    # Missing credential path
    res_no_cred = main([
        "--add-account",
        "--provider", "claude",
        "--label", "Test",
        "--config-path", str(config_path),
    ])
    assert res_no_cred == 1
    err = capsys.readouterr().err
    assert "Parâmetro --credential-path / --dir é obrigatório" in err


def test_cli_add_account_entrypoint(tmp_path):
    venv_bin = os.path.join(os.path.dirname(sys.executable), "ai-usage-collector")
    if not os.path.exists(venv_bin):
        pytest.skip("ai-usage-collector executable not found")

    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    cred_file = tmp_path / "auth.json"
    cred_file.write_text(json.dumps({"tokens": {"access_token": "abc"}}))

    cmd = [
        venv_bin,
        "--add-account",
        "--provider", "codex",
        "--label", "Codex CLI Test",
        "--credential-path", str(cred_file),
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "adicionada com sucesso" in res.stdout
