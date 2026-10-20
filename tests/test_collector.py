from datetime import datetime, timezone, timedelta
import json
import sqlite3
from ai_usage_collector.collector import collect_and_save, save_status_cache
from ai_usage_collector.config import save_config
from ai_usage_collector.contract import validate_status_contract


def test_collector_with_manual_invite_urls(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "claude-work",
                        "label": "Claude Trabalho",
                        "source": "manual",
                        "credential_path": str(tmp_path / "missing_claude.json"),
                        "manual_invite_url": "https://claude.ai/invite/promo-123",
                    }
                ]
            },
            "codex": {
                "accounts": [
                    {
                        "id": "codex-personal",
                        "label": "Codex Pessoal",
                        "source": "manual",
                        "credential_path": str(tmp_path / "missing_codex.json"),
                        "manual_invite_url": "https://chatgpt.com/invite/codex-456",
                    }
                ]
            },
            "gemini": {
                "accounts": [
                    {
                        "id": "gemini-edu",
                        "label": "Gemini Educacional",
                        "source": "manual",
                        "credential_path": str(tmp_path / "missing_gemini.json"),
                        "manual_invite_url": None,
                    }
                ]
            },
        },
    }
    save_config(cfg, config_path)

    status = collect_and_save(config_path=config_path, cache_path=cache_path)

    claude_accounts = status["agents"]["claude"]["accounts"]
    assert len(claude_accounts) == 1
    assert claude_accounts[0]["id"] == "claude-work"
    assert claude_accounts[0]["label"] == "Claude Trabalho"
    assert claude_accounts[0]["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/promo-123"
    assert claude_accounts[0]["health"]["status"] == "missing_credentials"

    codex_accounts = status["agents"]["codex"]["accounts"]
    assert len(codex_accounts) == 1
    assert codex_accounts[0]["free_trial_invites"]["invite_url"] == "https://chatgpt.com/invite/codex-456"

    gemini_accounts = status["agents"]["gemini"]["accounts"]
    assert len(gemini_accounts) == 1
    assert gemini_accounts[0]["free_trial_invites"]["invite_url"] is None


def test_collector_consolidates_all_three_providers_simultaneously(tmp_path):
    now = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
    now_sec = int(now.timestamp())
    now_ms = int(now.timestamp() * 1000)

    # 1. Claude setup
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    (claude_dir / ".credentials.json").write_text(
        json.dumps({
            "claudeAiOauth": {
                "accessToken": "sk-ant-test",
                "subscriptionType": "pro",
                "expiresAt": (now + timedelta(days=5)).isoformat(),
            }
        })
    )
    with open(claude_dir / "history.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": now_ms - (3600 * 1000)}) + "\n")

    # 2. Codex setup
    codex_dir = tmp_path / "codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(
        json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {"access_token": "valid_codex"},
        })
    )
    db_codex = codex_dir / "thread_history_1.sqlite"
    conn_codex = sqlite3.connect(db_codex)
    conn_codex.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, started_at INTEGER, completed_at INTEGER, status TEXT)")
    conn_codex.execute("INSERT INTO thread_turns VALUES ('t1', 'turn1', ?, ?, 'completed')", (now_sec - 1800, now_sec - 1790))
    conn_codex.commit()
    conn_codex.close()

    # 3. Gemini setup
    gemini_dir = tmp_path / "gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_text(
        json.dumps({
            "access_token": "ya29.test",
            "refresh_token": "1//refresh",
        })
    )
    db_gemini = gemini_dir / "conversation_summaries.db"
    conn_gem = sqlite3.connect(db_gemini)
    conn_gem.execute("CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, step_count INTEGER, last_modified_time DATETIME, last_user_input_time DATETIME)")
    conn_gem.execute("INSERT INTO conversation_summaries VALUES ('c1', 12, ?, ?)", (now.isoformat(), now.isoformat()))
    conn_gem.commit()
    conn_gem.close()

    # Config combining all 3
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cfg = {
        "version": 1,
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "claude-main",
                        "label": "Claude Principal",
                        "source": "auto",
                        "claude_dir": str(claude_dir),
                        "credential_path": str(claude_dir / ".credentials.json"),
                    }
                ]
            },
            "codex": {
                "accounts": [
                    {
                        "id": "codex-main",
                        "label": "Codex Principal",
                        "source": "auto",
                        "codex_dir": str(codex_dir),
                        "credential_path": str(codex_dir / "auth.json"),
                    }
                ]
            },
            "gemini": {
                "accounts": [
                    {
                        "id": "gemini-main",
                        "label": "Gemini Principal",
                        "source": "auto",
                        "gemini_dir": str(gemini_dir),
                        "credential_path": str(gemini_dir / "oauth_creds.json"),
                    }
                ]
            },
        },
    }
    save_config(cfg, config_path)

    status = collect_and_save(config_path=config_path, cache_path=cache_path, now=now)

    # Validations
    assert validate_status_contract(status)

    agents = status["agents"]
    assert agents["claude"]["status"] == "ok"
    assert agents["codex"]["status"] == "ok"
    assert agents["gemini"]["status"] == "ok"

    # Claude window check
    cl_acc = agents["claude"]["accounts"][0]
    assert cl_acc["native_window"]["type"] == "5h"
    assert cl_acc["native_window"]["used_capacity"] == 1

    # Codex window check
    co_acc = agents["codex"]["accounts"][0]
    assert co_acc["native_window"]["type"] == "3h"
    assert co_acc["native_window"]["used_capacity"] == 1

    # Gemini window check
    ge_acc = agents["gemini"]["accounts"][0]
    assert ge_acc["native_window"]["type"] == "daily"
    assert ge_acc["native_window"]["used_capacity"] == 1
