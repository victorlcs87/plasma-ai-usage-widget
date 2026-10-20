"""Tests for CLI --interactive-login, terminal emulator detection, and profile isolation."""

import base64
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_usage_collector.capture import (
    build_login_command_for_provider,
    build_terminal_exec_args,
    detect_terminal_emulator,
    inspect_and_validate_profile_credentials,
    run_interactive_login,
    validate_credentials_data,
)
from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config


def make_jwt(payload: dict) -> str:
    """Helper to generate a mock JWT token."""
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header_b64}.{payload_b64}.sig"


def test_build_login_command_for_all_providers(tmp_path: Path):
    prof_dir = tmp_path / "mock_profile"
    prof_dir.mkdir()

    # Claude
    cmd_claude, env_claude = build_login_command_for_provider("claude", prof_dir)
    assert f"env CLAUDE_CONFIG_DIR={prof_dir.resolve()} claude auth login" in cmd_claude
    assert env_claude["CLAUDE_CONFIG_DIR"] == str(prof_dir.resolve())

    # Codex
    cmd_codex, env_codex = build_login_command_for_provider("codex", prof_dir)
    assert f"env CODEX_HOME={prof_dir.resolve()} codex login" in cmd_codex
    assert env_codex["CODEX_HOME"] == str(prof_dir.resolve())

    # Gemini
    cmd_gemini, env_gemini = build_login_command_for_provider("gemini", prof_dir)
    assert cmd_gemini == "agy"
    assert env_gemini["GEMINI_CONFIG_DIR"] == str(prof_dir.resolve())

    # Unsupported provider
    with pytest.raises(ValueError, match="não suportado"):
        build_login_command_for_provider("unsupported", prof_dir)


def test_detect_terminal_emulator(monkeypatch):
    # Case 1: Custom $TERMINAL set and found
    monkeypatch.setenv("TERMINAL", "my-custom-term")
    with patch("shutil.which", side_effect=lambda x: f"/bin/{x}" if x == "my-custom-term" else None):
        assert detect_terminal_emulator() == "/bin/my-custom-term"

    # Case 2: $TERMINAL not set, konsole available
    monkeypatch.delenv("TERMINAL", raising=False)
    with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}" if x == "konsole" else None):
        assert detect_terminal_emulator() == "/usr/bin/konsole"

    # Case 3: x-terminal-emulator fallback
    with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}" if x == "x-terminal-emulator" else None):
        assert detect_terminal_emulator() == "/usr/bin/x-terminal-emulator"

    # Case 4: gnome-terminal fallback
    with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}" if x == "gnome-terminal" else None):
        assert detect_terminal_emulator() == "/usr/bin/gnome-terminal"

    # Case 5: xterm fallback
    with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}" if x == "xterm" else None):
        assert detect_terminal_emulator() == "/usr/bin/xterm"

    # Case 6: None available
    with patch("shutil.which", return_value=None):
        assert detect_terminal_emulator() is None


def test_build_terminal_exec_args():
    # konsole: -e bash -c cmd
    args_konsole = build_terminal_exec_args("/usr/bin/konsole", "claude auth login")
    assert args_konsole == ["/usr/bin/konsole", "-e", "bash", "-c", "claude auth login"]

    # gnome-terminal: -- bash -c cmd
    args_gnome = build_terminal_exec_args("/usr/bin/gnome-terminal", "codex login")
    assert args_gnome == ["/usr/bin/gnome-terminal", "--", "bash", "-c", "codex login"]

    # x-terminal-emulator: -e bash -c cmd
    args_xterm_emu = build_terminal_exec_args("/usr/bin/x-terminal-emulator", "agy")
    assert args_xterm_emu == ["/usr/bin/x-terminal-emulator", "-e", "bash", "-c", "agy"]


def test_validate_credentials_data():
    # Valid Claude
    jwt_tok = make_jwt({"email": "valid.claude@anthropic.com"})
    valid, msg, identity = validate_credentials_data("claude", {
        "claudeAiOauth": {"accessToken": jwt_tok}
    })
    assert valid is True
    assert identity == "valid.claude@anthropic.com"

    # Invalid Claude
    valid, msg, _ = validate_credentials_data("claude", {})
    assert valid is False
    assert "accessToken ausente" in msg

    # Valid Codex
    valid, msg, identity = validate_credentials_data("codex", {
        "tokens": {
            "access_token": "sk-access-token",
            "id_token": make_jwt({"email": "valid.codex@openai.com"}),
        }
    })
    assert valid is True
    assert identity == "valid.codex@openai.com"

    # Invalid Codex
    valid, msg, _ = validate_credentials_data("codex", {"tokens": {}})
    assert valid is False
    assert "access_token ausente" in msg

    # Valid Gemini
    valid, msg, identity = validate_credentials_data("gemini", {
        "access_token": "ya29.test",
        "email": "gemini@google.com",
    })
    assert valid is True
    assert identity == "gemini@google.com"

    # Invalid Gemini
    valid, msg, _ = validate_credentials_data("gemini", {})
    assert valid is False


def test_interactive_login_claude_no_terminal_success(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    user_jwt = make_jwt({"email": "developer@claude.ai", "sub": "user_dev_1"})

    def mock_subprocess_run(cmd, *args, **kwargs):
        # cmd is ["bash", "-c", ...]
        # Write .credentials.json in the directory specified by CLAUDE_CONFIG_DIR
        env = kwargs.get("env", os.environ)
        prof_dir = Path(env["CLAUDE_CONFIG_DIR"])
        cred_path = prof_dir / ".credentials.json"
        cred_path.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": user_jwt,
                "subscriptionType": "team",
            }
        }))
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        code = main([
            "--interactive-login", "claude",
            "--no-terminal",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 0
    assert "Login interativo de 'claude' concluído com sucesso" in captured.out
    assert "developer@claude.ai" in captured.out

    # Verify config persistence
    cfg = load_config(config_path)
    claude_accs = cfg["agents"]["claude"]["accounts"]
    acc = next((a for a in claude_accs if a["source"] == "interactive_login"), None)
    assert acc is not None
    assert "developer@claude.ai" in acc["name"]

    # Verify profile directory permissions (0700) and credential permissions (0600)
    profile_dir = Path(acc["claude_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    cred_file = Path(acc["credential_path"])
    assert cred_file.exists()
    assert stat.S_IMODE(os.stat(cred_file).st_mode) == 0o600

    # Verify status.json cache was synchronized
    assert cache_path.exists()
    with open(cache_path, "r", encoding="utf-8") as f:
        status_data = json.load(f)
    assert any(a["id"] == acc["id"] for a in status_data["agents"]["claude"]["accounts"])


def test_interactive_login_codex_with_terminal_emulator(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    user_jwt = make_jwt({"email": "ai.expert@openai.com"})
    terminal_called_with = []

    def mock_detect_term():
        return "/usr/bin/konsole"

    def mock_subprocess_run(cmd, *args, **kwargs):
        terminal_called_with.append(list(cmd))
        env = kwargs.get("env", os.environ)
        prof_dir = Path(env["CODEX_HOME"])
        auth_file = prof_dir / "auth.json"
        auth_file.write_text(json.dumps({
            "tokens": {
                "access_token": "sk-codex-test-token-777",
                "id_token": user_jwt,
            }
        }))
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("ai_usage_collector.capture.detect_terminal_emulator", side_effect=mock_detect_term), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        code = main([
            "--interactive-login", "codex",
            "--name", "Codex Especial",
            "--invite-url", "https://chatgpt.com/invite/123",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 0
    assert "Codex Especial" in captured.out
    konsole_calls = [c for c in terminal_called_with if c[0] == "/usr/bin/konsole"]
    assert len(konsole_calls) == 1
    # Verify terminal args
    assert konsole_calls[0][0] == "/usr/bin/konsole"
    assert konsole_calls[0][1] == "-e"

    cfg = load_config(config_path)
    codex_accs = cfg["agents"]["codex"]["accounts"]
    acc = next((a for a in codex_accs if a.get("name") == "Codex Especial"), None)
    assert acc is not None
    assert acc["manual_invite_url"] == "https://chatgpt.com/invite/123"

    profile_dir = Path(acc["codex_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    cred_file = Path(acc["credential_path"])
    assert cred_file.exists()
    assert stat.S_IMODE(os.stat(cred_file).st_mode) == 0o600


def test_interactive_login_gemini_success(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    def mock_subprocess_run(cmd, *args, **kwargs):
        env = kwargs.get("env", os.environ)
        prof_dir = Path(env["GEMINI_CONFIG_DIR"])
        cred_file = prof_dir / "oauth_creds.json"
        cred_file.write_text(json.dumps({
            "access_token": "ya29.gemini_auth_key",
            "email": "user.gemini@google.com",
        }))
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        code = main([
            "--interactive-login", "gemini",
            "--no-terminal",
            "--total-capacity", "250",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 0
    assert "user.gemini@google.com" in captured.out

    cfg = load_config(config_path)
    gemini_accs = cfg["agents"]["gemini"]["accounts"]
    acc = next((a for a in gemini_accs if a["source"] == "interactive_login"), None)
    assert acc is not None
    assert acc["rate_limit_capacity"] == 250

    profile_dir = Path(acc["gemini_dir"])
    assert profile_dir.exists()
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700


def test_interactive_login_cancelled_or_missing_credentials(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # Terminal closes without writing credentials
    def mock_subprocess_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        code = main([
            "--interactive-login", "claude",
            "--no-terminal",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 1
    assert "Nenhuma credencial gerada ou válida no perfil isolado" in captured.err

    # Ensure config.json was not polluted with an interactive login account
    cfg = load_config(config_path)
    claude_accs = cfg.get("agents", {}).get("claude", {}).get("accounts", [])
    assert not any(a.get("source") == "interactive_login" for a in claude_accs)


def test_interactive_login_missing_terminal_error(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # No terminal available and not a tty
    monkeypatch.setattr("ai_usage_collector.capture.detect_terminal_emulator", lambda: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    code = main([
        "--interactive-login", "claude",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])

    captured = capsys.readouterr()
    assert code == 1
    assert "Nenhum emulador de terminal compatível encontrado" in captured.err
    assert "--no-terminal" in captured.err


def test_interactive_login_with_status_flag(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    def mock_subprocess_run(cmd, *args, **kwargs):
        env = kwargs.get("env", os.environ)
        prof_dir = Path(env["CLAUDE_CONFIG_DIR"])
        (prof_dir / ".credentials.json").write_text(json.dumps({
            "claudeAiOauth": {"accessToken": make_jwt({"email": "status.test@claude.com"})}
        }))
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        code = main([
            "--interactive-login", "claude",
            "--no-terminal",
            "--status",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ])

    captured = capsys.readouterr()
    assert code == 0
    assert "Login interativo de 'claude' concluído com sucesso" in captured.out

    # Must contain json status payload
    json_start = captured.out.find("{")
    assert json_start != -1
    parsed = json.loads(captured.out[json_start:])
    assert parsed["version"] == 1
    assert any("status.test@claude.com" in a.get("label", "") for a in parsed["agents"]["claude"]["accounts"])


def test_interactive_login_missing_provider(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    code = main([
        "--interactive-login",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert "Parâmetro do provedor é obrigatório para --interactive-login" in captured.err


def test_interactive_login_invalid_provider(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    code = main([
        "--interactive-login", "invalid_agent",
        "--config-path", str(config_path),
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert "Provedor 'invalid_agent' não suportado" in captured.err


def test_interactive_login_duplicate_slug_handling(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    def mock_subprocess_run(cmd, *args, **kwargs):
        env = kwargs.get("env", os.environ)
        prof_dir = Path(env["CLAUDE_CONFIG_DIR"])
        (prof_dir / ".credentials.json").write_text(json.dumps({
            "claudeAiOauth": {"accessToken": make_jwt({"email": "shared@domain.com"})}
        }))
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        # 1st interactive login
        assert main([
            "--interactive-login", "claude",
            "--no-terminal",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ]) == 0
        capsys.readouterr()

        # 2nd interactive login with same identity
        assert main([
            "--interactive-login", "claude",
            "--no-terminal",
            "--config-path", str(config_path),
            "--cache-path", str(cache_path),
        ]) == 0
        capsys.readouterr()

    cfg = load_config(config_path)
    claude_accs = [a for a in cfg["agents"]["claude"]["accounts"] if a["source"] == "interactive_login"]
    assert len(claude_accs) == 2
    assert claude_accs[0]["id"] != claude_accs[1]["id"]
    assert claude_accs[0]["claude_dir"] != claude_accs[1]["claude_dir"]


def test_interactive_login_rollback_on_config_failure(capsys, tmp_path):
    """Verify that profile dir is completely cleaned up if saving config fails during interactive login."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    def mock_subprocess_run(cmd, *args, **kwargs):
        env = kwargs.get("env", os.environ)
        prof_dir = Path(env["CLAUDE_CONFIG_DIR"])
        (prof_dir / ".credentials.json").write_text(json.dumps({
            "claudeAiOauth": {"accessToken": make_jwt({"email": "fail@test.com"})}
        }))
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("ai_usage_collector.capture.save_config", side_effect=IOError("Simulated disk error")):
        code = main([
            "--interactive-login", "claude",
            "--no-terminal",
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


def test_interactive_login_recursive_permissions(tmp_path):
    """Verify that all files in profile directory get 0600 and directories get 0700."""
    from ai_usage_collector.capture import enforce_profile_security_permissions

    test_prof = tmp_path / "test_prof"
    test_prof.mkdir()
    sub_dir = test_prof / "subdir"
    sub_dir.mkdir()
    f1 = test_prof / "cred.json"
    f1.write_text("{}")
    f2 = sub_dir / "token.txt"
    f2.write_text("secret")

    # Give them lax permissions initially
    os.chmod(f1, 0o666)
    os.chmod(f2, 0o644)
    os.chmod(sub_dir, 0o777)
    os.chmod(test_prof, 0o755)

    enforce_profile_security_permissions(test_prof)

    assert stat.S_IMODE(os.stat(test_prof).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(sub_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(f1).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(f2).st_mode) == 0o600

