"""Tests for CLI --capture-current and profile isolation."""

import base64
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config


def make_jwt(payload: dict) -> str:
    """Helper to generate a mock JWT token."""
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header_b64}.{payload_b64}.sig"


def test_capture_current_claude_success(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    source_dir = tmp_path / "source_claude"
    source_dir.mkdir()
    cred_file = source_dir / ".credentials.json"
    jwt_tok = make_jwt({"email": "claude.dev@anthropic.com", "sub": "usr_claude123"})
    cred_file.write_text(json.dumps({
        "claudeAiOauth": {
            "accessToken": jwt_tok,
            "subscriptionType": "pro",
            "rateLimitTier": "default_claude_ai",
        }
    }))

    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(cred_file))

    code = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "capturada com sucesso" in captured.out
    assert "claude.dev@anthropic.com" in captured.out
    assert captured.err == ""

    # Verify config persistence
    cfg = load_config(config_path)
    claude_accs = cfg["agents"]["claude"]["accounts"]
    captured_acc = next((a for a in claude_accs if a["source"] == "captured"), None)
    assert captured_acc is not None
    assert "claude.dev@anthropic.com" in captured_acc["name"]

    # Verify profile directory and permissions
    profile_dir = Path(captured_acc["claude_dir"])
    assert profile_dir.exists()
    assert profile_dir.is_dir()
    dir_mode = stat.S_IMODE(os.stat(profile_dir).st_mode)
    assert dir_mode == 0o700

    isolated_cred = Path(captured_acc["credential_path"])
    assert isolated_cred.exists()
    assert isolated_cred.is_file()
    file_mode = stat.S_IMODE(os.stat(isolated_cred).st_mode)
    assert file_mode == 0o600

    # Ensure isolated credentials match the source data
    with open(isolated_cred, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["claudeAiOauth"]["accessToken"] == jwt_tok

    # Verify cache status.json synchronization
    assert cache_path.exists()
    with open(cache_path, "r", encoding="utf-8") as f:
        status_data = json.load(f)
    assert any(a["id"] == captured_acc["id"] for a in status_data["agents"]["claude"]["accounts"])


def test_capture_current_codex_success(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    source_dir = tmp_path / "source_codex"
    source_dir.mkdir()
    auth_file = source_dir / "auth.json"
    id_jwt = make_jwt({"email": "codex.user@openai.com"})
    auth_file.write_text(json.dumps({
        "tokens": {
            "access_token": "sk-access-token-12345",
            "id_token": id_jwt,
            "account_id": "act_openai_999",
        }
    }))

    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_file))

    code = main([
        "--capture-active", "codex",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "capturada com sucesso" in captured.out
    assert "codex.user@openai.com" in captured.out

    cfg = load_config(config_path)
    codex_accs = cfg["agents"]["codex"]["accounts"]
    captured_acc = next((a for a in codex_accs if a["source"] == "captured"), None)
    assert captured_acc is not None
    assert "codex.user@openai.com" in captured_acc["name"]

    profile_dir = Path(captured_acc["codex_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    isolated_auth = Path(captured_acc["credential_path"])
    assert isolated_auth.exists()
    assert stat.S_IMODE(os.stat(isolated_auth).st_mode) == 0o600


def test_capture_current_gemini_file_success(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    source_dir = tmp_path / "source_gemini"
    source_dir.mkdir()
    gemini_file = source_dir / "oauth_creds.json"
    gemini_file.write_text(json.dumps({
        "access_token": "ya29.test_token_gemini",
        "email": "gemini.tester@google.com",
    }))

    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", str(gemini_file))

    code = main([
        "--capture-current", "gemini",
        "--label", "Gemini Trabalho",
        "--invite-url", "https://gemini.google/invite/corp",
        "--total-capacity", "120",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "capturada com sucesso" in captured.out
    assert "Gemini Trabalho" in captured.out

    cfg = load_config(config_path)
    gemini_accs = cfg["agents"]["gemini"]["accounts"]
    captured_acc = next((a for a in gemini_accs if a.get("name") == "Gemini Trabalho"), None)
    assert captured_acc is not None
    assert captured_acc["manual_invite_url"] == "https://gemini.google/invite/corp"
    assert captured_acc["rate_limit_capacity"] == 120

    profile_dir = Path(captured_acc["gemini_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    isolated_creds = Path(captured_acc["credential_path"])
    assert isolated_creds.exists()
    assert stat.S_IMODE(os.stat(isolated_creds).st_mode) == 0o600


def test_capture_current_gemini_keyring_success(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # Ensure no file matches
    monkeypatch.delenv("GEMINI_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_CONFIG_DIR", raising=False)

    keyring_payload = {
        "access_token": "ya29.keyring_gemini_token",
        "id_token": make_jwt({"email": "keyring.user@example.com"}),
    }

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "secret-tool" in cmd:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = json.dumps(keyring_payload)
            return mock_res
        return subprocess.run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        code = main([
            "--capture-current", "gemini",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 0
    assert "capturada com sucesso" in captured.out
    assert "keyring.user@example.com" in captured.out

    cfg = load_config(config_path)
    gemini_accs = cfg["agents"]["gemini"]["accounts"]
    captured_acc = next((a for a in gemini_accs if a["source"] == "captured"), None)
    assert captured_acc is not None
    assert "keyring.user@example.com" in captured_acc["name"]

    profile_dir = Path(captured_acc["gemini_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    isolated_creds = Path(captured_acc["credential_path"])
    assert isolated_creds.exists()
    assert stat.S_IMODE(os.stat(isolated_creds).st_mode) == 0o600


def test_capture_current_duplicate_slug_resolution(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    source_dir = tmp_path / "source_claude"
    source_dir.mkdir()
    cred_file = source_dir / ".credentials.json"
    cred_file.write_text(json.dumps({
        "accessToken": "sk-ant-test-token",
        "email": "duplicate@company.com",
    }))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(cred_file))

    # First capture
    code1 = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert code1 == 0
    capsys.readouterr()

    # Second capture with same identity and label
    code2 = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert code2 == 0
    capsys.readouterr()

    # Third capture
    code3 = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert code3 == 0
    capsys.readouterr()

    cfg = load_config(config_path)
    claude_accs = [a for a in cfg["agents"]["claude"]["accounts"] if a["source"] == "captured"]
    assert len(claude_accs) == 3

    ids = [a["id"] for a in claude_accs]
    assert len(set(ids)) == 3  # All IDs must be unique
    assert any(i.endswith("-2") for i in ids)
    assert any(i.endswith("-3") for i in ids)

    # All profile dirs must be distinct and exist
    dirs = [a["claude_dir"] for a in claude_accs]
    assert len(set(dirs)) == 3
    for d in dirs:
        p = Path(d)
        assert p.exists()
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o700


def test_capture_current_missing_session_error(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # Claude: non-existent file
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(tmp_path / "nonexistent_claude.json"))
    res_claude = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert res_claude == 1
    err_claude = capsys.readouterr().err
    assert "Nenhuma sessão ativa encontrada para Claude" in err_claude
    assert "claude auth login" in err_claude

    # Codex: non-existent file
    monkeypatch.setenv("CODEX_AUTH_PATH", str(tmp_path / "nonexistent_codex.json"))
    res_codex = main([
        "--capture-current", "codex",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert res_codex == 1
    err_codex = capsys.readouterr().err
    assert "Nenhuma sessão ativa encontrada para Codex" in err_codex
    assert "codex login" in err_codex

    # Gemini: non-existent file and failed keyring
    monkeypatch.delenv("GEMINI_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))

    def mock_secret_tool_fail(*args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stdout = ""
        return mock_res

    with patch("subprocess.run", side_effect=mock_secret_tool_fail):
        res_gemini = main([
            "--capture-current", "gemini",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])
    assert res_gemini == 1
    err_gemini = capsys.readouterr().err
    assert "Nenhuma sessão ativa encontrada para Gemini" in err_gemini


def test_capture_current_corrupt_or_empty_credentials(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # Claude with empty dict (no accessToken)
    bad_claude = tmp_path / "bad_claude.json"
    bad_claude.write_text(json.dumps({}))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(bad_claude))
    res = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert res == 1
    err = capsys.readouterr().err
    assert "accessToken ausente" in err

    # Codex with tokens missing access_token
    bad_codex = tmp_path / "bad_codex.json"
    bad_codex.write_text(json.dumps({"tokens": {}}))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(bad_codex))
    res = main([
        "--capture-current", "codex",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert res == 1
    err = capsys.readouterr().err
    assert "tokens.access_token ausente" in err


def test_capture_current_with_status_flag(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cred_file = tmp_path / ".credentials.json"
    cred_file.write_text(json.dumps({
        "accessToken": "sk-ant-test-token",
        "email": "user.status@domain.com",
    }))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(cred_file))

    code = main([
        "--capture-current", "claude",
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert "capturada com sucesso" in captured.out

    # Must contain json output because of --status
    json_start = captured.out.find("{")
    assert json_start != -1
    parsed_json = json.loads(captured.out[json_start:])
    assert parsed_json["version"] == 3
    assert any("user.status@domain.com" in a.get("label", "") for a in parsed_json["agents"]["claude"]["accounts"])


def test_capture_current_invalid_provider(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    code = main([
        "--capture-current", "unknown_ai",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert "Provedor 'unknown_ai' não suportado" in captured.err


def test_no_token_leakage_in_stdout_stderr(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    secret_token = "SUPER_SECRET_TOKEN_DO_NOT_LEAK_99887766"
    cred_file = tmp_path / ".credentials.json"
    cred_file.write_text(json.dumps({
        "accessToken": secret_token,
        "email": "safe.user@domain.com",
    }))
    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(cred_file))

    code = main([
        "--capture-current", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert secret_token not in captured.out
    assert secret_token not in captured.err


def test_cli_executable_capture_current(tmp_path, monkeypatch):
    venv_bin = os.path.join(os.path.dirname(sys.executable), "ai-usage-collector")
    if not os.path.exists(venv_bin):
        pytest.skip("ai-usage-collector executable not found")

    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    cred_file = tmp_path / "auth.json"
    cred_file.write_text(json.dumps({
        "tokens": {
            "access_token": "sk-cli-token-abc",
            "account_id": "act-cli-test",
        }
    }))

    env = os.environ.copy()
    env["CODEX_AUTH_PATH"] = str(cred_file)

    cmd = [
        venv_bin,
        "--capture-current", "codex",
        "--name", "Codex Executable Test",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "capturada com sucesso" in res.stdout
    assert "Codex Executable Test" in res.stdout


def test_capture_current_rollback_on_failure(capsys, tmp_path, monkeypatch):
    """Verify that profiles dir is removed/rolled back if saving config fails."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    cred_file = tmp_path / "auth.json"
    cred_file.write_text(json.dumps({
        "tokens": {"access_token": "sk-token", "account_id": "act-test"}
    }))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(cred_file))

    from unittest.mock import patch
    with patch("ai_usage_collector.capture.save_config", side_effect=IOError("Disk write failed")):
        code = main([
            "--capture-current", "codex",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 1
    assert "Falha ao salvar configuração" in captured.err

    # Profile directory should NOT remain on disk
    profiles_base = tmp_path / "profiles"
    if profiles_base.exists():
        subdirs = [p for p in profiles_base.iterdir() if p.is_dir()]
        assert len(subdirs) == 0


def test_capture_current_recursive_permissions(tmp_path, monkeypatch):
    """Verify that all files in profile directory have 0600 and directory has 0700."""
    config_path = tmp_path / "config.json"
    cred_file = tmp_path / "auth.json"
    cred_file.write_text(json.dumps({
        "tokens": {"access_token": "sk-token", "account_id": "act-test"}
    }))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(cred_file))

    from ai_usage_collector.capture import capture_current_session
    success, msg, acc = capture_current_session("codex", config_path=config_path)
    assert success
    assert acc is not None

    profile_dir = Path(acc["codex_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    cred_path = Path(acc["credential_path"])
    assert cred_path.exists()
    assert stat.S_IMODE(os.stat(cred_path).st_mode) == 0o600

