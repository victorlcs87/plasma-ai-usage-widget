import json
from ai_usage_collector.collector import collect_and_save, save_status_cache
from ai_usage_collector.config import save_config


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
