"""Tests for CLI --switch-account / --activate-account functionality and automatic active account detection."""

import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_usage_collector.cli import main
from ai_usage_collector.collector import collect_and_save, switch_account
from ai_usage_collector.config import load_config, save_config, save_secure_json


def test_cli_switch_account_claude_success(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_claude_path = tmp_path / "sys" / "claude" / ".credentials.json"
    profile_pessoal = tmp_path / "profiles" / "claude-pessoal" / ".credentials.json"
    profile_trabalho = tmp_path / "profiles" / "claude-trabalho" / ".credentials.json"

    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(sys_claude_path))

    creds_pessoal = {
        "claudeAiOauth": {
            "accessToken": "token-pessoal-123",
            "refreshToken": "refresh-pessoal",
            "email": "pessoal@example.com",
            "subscriptionType": "pro",
        }
    }
    creds_trabalho = {
        "claudeAiOauth": {
            "accessToken": "token-trabalho-456",
            "refreshToken": "refresh-trabalho",
            "email": "trabalho@example.com",
            "subscriptionType": "team",
        }
    }

    save_secure_json(creds_pessoal, profile_pessoal)
    save_secure_json(creds_trabalho, profile_trabalho)
    # System currently has credentials from pessoal
    save_secure_json(creds_pessoal, sys_claude_path)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "claude-pessoal",
                        "label": "Claude Pessoal",
                        "source": "captured",
                        "credential_path": str(profile_pessoal),
                        "active": True,
                    },
                    {
                        "id": "claude-trabalho",
                        "label": "Claude Trabalho",
                        "source": "captured",
                        "credential_path": str(profile_trabalho),
                        "active": False,
                    },
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    # Perform switch to claude-trabalho
    code = main([
        "--switch-account", "claude", "claude-trabalho",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'Claude Trabalho' ativada com sucesso no sistema!" in captured.out
    assert captured.err == ""

    # Verify system file was updated with trabalho credentials
    with open(sys_claude_path, "r", encoding="utf-8") as f:
        activated_creds = json.load(f)
    assert activated_creds["claudeAiOauth"]["accessToken"] == "token-trabalho-456"
    assert activated_creds["claudeAiOauth"]["email"] == "trabalho@example.com"

    # Verify 0600 permissions on system file and 0700 on dir
    assert stat.S_IMODE(os.stat(sys_claude_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(sys_claude_path.parent).st_mode) == 0o700

    # Campo `active` deixou de ser fonte de verdade e e removido da configuracao (ADR-0008)
    updated_cfg = load_config(config_path)
    accs = updated_cfg["agents"]["claude"]["accounts"]
    assert [a["id"] for a in accs] == ["claude-pessoal", "claude-trabalho"]
    assert all("active" not in a for a in accs)

    # Verify status.json has isActive
    assert cache_path.exists()
    with open(cache_path, "r", encoding="utf-8") as f:
        status_data = json.load(f)
    status_accs = status_data["agents"]["claude"]["accounts"]
    assert len(status_accs) == 2
    assert status_accs[0]["id"] == "claude-pessoal" and status_accs[0]["isActive"] is False
    assert status_accs[1]["id"] == "claude-trabalho" and status_accs[1]["isActive"] is True


def test_cli_switch_account_codex_success(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_codex_path = tmp_path / "sys" / "codex" / "auth.json"
    profile_1 = tmp_path / "profiles" / "codex-1" / "auth.json"
    profile_2 = tmp_path / "profiles" / "codex-2" / "auth.json"

    monkeypatch.setenv("CODEX_AUTH_PATH", str(sys_codex_path))

    creds_1 = {
        "tokens": {
            "access_token": "codex-token-1",
            "refresh_token": "codex-refresh-1",
            "account_id": "acc-codex-1",
        }
    }
    creds_2 = {
        "tokens": {
            "access_token": "codex-token-2",
            "refresh_token": "codex-refresh-2",
            "account_id": "acc-codex-2",
        }
    }

    save_secure_json(creds_1, profile_1)
    save_secure_json(creds_2, profile_2)
    save_secure_json(creds_1, sys_codex_path)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {"accounts": []},
            "codex": {
                "accounts": [
                    {"id": "codex-1", "label": "Codex Dev", "credential_path": str(profile_1), "active": True},
                    {"id": "codex-2", "label": "Codex Prod", "credential_path": str(profile_2), "active": False},
                ]
            },
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    # Perform switch to codex-2
    code = main([
        "--switch-account", "codex", "codex-2",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'Codex Prod' ativada com sucesso no sistema!" in captured.out

    with open(sys_codex_path, "r", encoding="utf-8") as f:
        activated = json.load(f)
    assert activated["tokens"]["access_token"] == "codex-token-2"
    assert stat.S_IMODE(os.stat(sys_codex_path).st_mode) == 0o600

    # Verify status.json
    with open(cache_path, "r", encoding="utf-8") as f:
        status_data = json.load(f)
    assert status_data["agents"]["codex"]["accounts"][0]["isActive"] is False
    assert status_data["agents"]["codex"]["accounts"][1]["isActive"] is True


def test_cli_switch_account_gemini_with_keyring_call(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_gemini_path = Path(os.environ["HOME"]) / ".gemini" / "oauth_creds.json"  # HOME falso (conftest)
    profile_1 = tmp_path / "profiles" / "gemini-1" / "oauth_creds.json"
    profile_2 = tmp_path / "profiles" / "gemini-2" / "oauth_creds.json"

    monkeypatch.delenv("GEMINI_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_CONFIG_DIR", raising=False)

    creds_1 = {
        "access_token": "gem-tok-1",
        "refresh_token": "gem-ref-1",
        "email": "user1@gmail.com",
    }
    creds_2 = {
        "access_token": "gem-tok-2",
        "refresh_token": "gem-ref-2",
        "email": "user2@gmail.com",
    }

    save_secure_json(creds_1, profile_1)
    save_secure_json(creds_2, profile_2)
    save_secure_json(creds_1, sys_gemini_path)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {"accounts": []},
            "codex": {"accounts": []},
            "gemini": {
                "accounts": [
                    {"id": "gem-1", "label": "Gemini 1", "credential_path": str(profile_1), "active": True},
                    {"id": "gem-2", "label": "Gemini 2", "credential_path": str(profile_2), "active": False},
                ]
            },
        },
    }
    save_config(cfg, config_path)

    real_run = subprocess.run
    called_commands: list[list[str]] = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[0] == "secret-tool":
            called_commands.append(cmd)
            mock_proc = MagicMock()
            mock_proc.returncode = 1 if "lookup" in cmd else 0  # chaveiro vazio
            mock_proc.stdout = ""
            return mock_proc
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    code = main([
        "--switch-account", "gemini", "gem-2",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'Gemini 2' ativada com sucesso no sistema!" in captured.out

    # Verify secret-tool was called to store new Gemini credentials
    store_calls = [cmd for cmd in called_commands if "store" in cmd]
    assert len(store_calls) >= 1
    assert "service" in store_calls[0] and "gemini" in store_calls[0]

    # Verify file saved
    with open(sys_gemini_path, "r", encoding="utf-8") as f:
        activated = json.load(f)
    assert activated["access_token"] == "gem-tok-2"
    assert stat.S_IMODE(os.stat(sys_gemini_path).st_mode) == 0o600


def test_cli_switch_account_backups_renewed_tokens_prior_to_switch(capsys, tmp_path, monkeypatch):
    """Test that refreshed token generated in system CLI session is synced back to its profile before switching."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_claude_path = tmp_path / "sys" / "claude" / ".credentials.json"
    profile_1 = tmp_path / "profiles" / "claude-1" / ".credentials.json"
    profile_2 = tmp_path / "profiles" / "claude-2" / ".credentials.json"

    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(sys_claude_path))

    old_profile_1_creds = {
        "claudeAiOauth": {
            "accessToken": "old-token-1",
            "refreshToken": "common-refresh-1",
            "email": "user1@test.com",
        }
    }
    profile_2_creds = {
        "claudeAiOauth": {
            "accessToken": "token-2",
            "refreshToken": "refresh-2",
            "email": "user2@test.com",
        }
    }
    # During usage, system CLI session refreshed the access token for account 1
    renewed_sys_creds = {
        "claudeAiOauth": {
            "accessToken": "renewed-token-super-fresh-1",
            "refreshToken": "common-refresh-1",
            "email": "user1@test.com",
        }
    }

    save_secure_json(old_profile_1_creds, profile_1)
    save_secure_json(profile_2_creds, profile_2)
    save_secure_json(renewed_sys_creds, sys_claude_path)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "claude-1", "label": "Claude 1", "credential_path": str(profile_1), "active": True},
                    {"id": "claude-2", "label": "Claude 2", "credential_path": str(profile_2), "active": False},
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    # Perform switch to claude-2
    code = main([
        "--switch-account", "claude", "claude-2",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    assert code == 0

    # Verify that profile 1 received the renewed access token before the system was switched!
    with open(profile_1, "r", encoding="utf-8") as f:
        synced_profile_1 = json.load(f)
    assert synced_profile_1["claudeAiOauth"]["accessToken"] == "renewed-token-super-fresh-1"
    assert stat.S_IMODE(os.stat(profile_1).st_mode) == 0o600

    # Verify that system now contains profile 2
    with open(sys_claude_path, "r", encoding="utf-8") as f:
        current_sys = json.load(f)
    assert current_sys["claudeAiOauth"]["accessToken"] == "token-2"


def test_cli_switch_account_validation_errors(capsys, tmp_path):
    config_path = tmp_path / "config.json"
    cfg = {"version": 1, "agents": {"claude": {"accounts": [{"id": "acc-1", "label": "Conta 1"}]}}}
    save_config(cfg, config_path)

    # Invalid provider
    code_prov = main(["--switch-account", "unknown_prov", "acc-1", "--config-path", str(config_path)])
    cap_prov = capsys.readouterr()
    assert code_prov == 1
    assert "Provedor inválido" in cap_prov.err

    # Account not found
    code_acc = main(["--switch-account", "claude", "non-existent-acc", "--config-path", str(config_path)])
    cap_acc = capsys.readouterr()
    assert code_acc == 1
    assert "não encontrada" in cap_acc.err


def test_cli_switch_account_with_status_output(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_claude = tmp_path / "sys" / ".credentials.json"
    prof_1 = tmp_path / "prof1" / ".credentials.json"

    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(sys_claude))

    save_secure_json({"accessToken": "tok-1", "email": "a@b.com"}, prof_1)
    save_secure_json({"accessToken": "tok-1", "email": "a@b.com"}, sys_claude)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {"accounts": [{"id": "c-1", "label": "C1", "credential_path": str(prof_1)}]},
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    code = main([
        "--switch-account", "claude", "c-1",
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'C1' já está ativa no sistema" in captured.out
    # Output must also include valid JSON payload with isActive: true
    lines = captured.out.strip().split("\n", 1)
    json_part = lines[1] if len(lines) > 1 else ""
    parsed = json.loads(json_part)
    assert parsed["agents"]["claude"]["accounts"][0]["isActive"] is True


def test_cli_activate_account_alias(capsys, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_claude = tmp_path / "sys" / ".credentials.json"
    prof_1 = tmp_path / "prof1" / ".credentials.json"

    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(sys_claude))

    save_secure_json({"accessToken": "tok-1", "email": "a@b.com"}, prof_1)
    save_secure_json({"accessToken": "tok-1", "email": "a@b.com"}, sys_claude)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {"accounts": [{"id": "c-1", "label": "C1", "credential_path": str(prof_1)}]},
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    code = main([
        "--activate-account", "claude", "c-1",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert "Conta 'C1' já está ativa no sistema" in captured.out


def test_auto_detection_in_collect_and_save(tmp_path, monkeypatch):
    """Verify that collect_and_save identifies active account even without explicit switch."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    sys_claude = tmp_path / "sys" / ".credentials.json"
    prof_1 = tmp_path / "prof1" / ".credentials.json"
    prof_2 = tmp_path / "prof2" / ".credentials.json"

    monkeypatch.setenv("CLAUDE_CREDENTIALS_PATH", str(sys_claude))

    save_secure_json({"accessToken": "tok-1", "email": "user1@b.com"}, prof_1)
    save_secure_json({"accessToken": "tok-2", "email": "user2@b.com"}, prof_2)
    # System currently has tok-2
    save_secure_json({"accessToken": "tok-2", "email": "user2@b.com"}, sys_claude)

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {"id": "c-1", "label": "C1", "credential_path": str(prof_1)},
                    {"id": "c-2", "label": "C2", "credential_path": str(prof_2)},
                ]
            },
            "codex": {"accounts": []},
            "gemini": {"accounts": []},
        },
    }
    save_config(cfg, config_path)

    status_data = collect_and_save(config_path=config_path, cache_path=cache_path)
    c_accs = status_data["agents"]["claude"]["accounts"]

    assert c_accs[0]["id"] == "c-1" and c_accs[0]["isActive"] is False
    assert c_accs[1]["id"] == "c-2" and c_accs[1]["isActive"] is True


def _single_default_cfg(provider: str, sys_path: Path) -> dict:
    agents = {p: {"accounts": []} for p in ("claude", "codex", "gemini")}
    agents[provider]["accounts"] = [{
        "id": "default", "label": f"{provider.capitalize()} (Padrão)", "source": "auto",
        "credential_path": str(sys_path),
    }]
    return {"version": 1, "agents": agents}


def test_codex_default_on_system_path_stays_active_without_duplicates(tmp_path, monkeypatch):
    """Sem adaptador de identidade (ticket 19), Codex mantem o comportamento anterior."""
    config_path, cache_path = tmp_path / "config.json", tmp_path / "status.json"
    sys_codex = tmp_path / "sys" / "auth.json"
    monkeypatch.setenv("CODEX_AUTH_PATH", str(sys_codex))
    save_secure_json({"tokens": {"access_token": "cx-a", "refresh_token": "cx-r", "account_id": "acct1"}}, sys_codex)
    save_config(_single_default_cfg("codex", sys_codex), config_path)

    status = collect_and_save(config_path=config_path, cache_path=cache_path)
    assert [(a["id"], a["isActive"]) for a in status["agents"]["codex"]["accounts"]] == [("default", True)]

    code = main(["--switch-account", "codex", "default",
                 "--config-path", str(config_path), "--cache-path", str(cache_path)])
    assert code == 0
    assert [a["id"] for a in load_config(config_path)["agents"]["codex"]["accounts"]] == ["default"]


def test_gemini_default_on_system_path_stays_active_without_duplicates(tmp_path, monkeypatch):
    """Sem adaptador de identidade (ticket 20), Gemini mantem o comportamento anterior."""
    config_path, cache_path = tmp_path / "config.json", tmp_path / "status.json"
    sys_gemini = tmp_path / "sys" / "oauth_creds.json"
    monkeypatch.setenv("GEMINI_CREDENTIALS_PATH", str(sys_gemini))
    save_secure_json({"access_token": "g-a", "refresh_token": "g-r", "email": "g@x.com"}, sys_gemini)
    save_config(_single_default_cfg("gemini", sys_gemini), config_path)

    status = collect_and_save(config_path=config_path, cache_path=cache_path)
    assert [(a["id"], a["isActive"]) for a in status["agents"]["gemini"]["accounts"]] == [("default", True)]

    code = main(["--switch-account", "gemini", "default",
                 "--config-path", str(config_path), "--cache-path", str(cache_path)])
    assert code == 0
    assert [a["id"] for a in load_config(config_path)["agents"]["gemini"]["accounts"]] == ["default"]
