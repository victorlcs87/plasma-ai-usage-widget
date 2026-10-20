from ai_usage_collector.contract import (
    build_empty_status_contract,
    build_agent_account_status,
    validate_status_contract,
    AGENT_NATIVE_WINDOWS,
)


def test_agent_native_windows_definition():
    assert AGENT_NATIVE_WINDOWS["claude"] == "5h"
    assert AGENT_NATIVE_WINDOWS["codex"] == "3h"
    assert AGENT_NATIVE_WINDOWS["gemini"] == "daily"


def test_build_empty_status_contract():
    contract = build_empty_status_contract()
    assert contract["version"] == 1
    assert "last_updated" in contract
    assert contract["status"] == "ok"
    assert "agents" in contract

    for agent in ["claude", "codex", "gemini"]:
        assert agent in contract["agents"]
        agent_data = contract["agents"][agent]
        assert "name" in agent_data
        assert "status" in agent_data
        assert isinstance(agent_data["accounts"], list)


def test_build_agent_account_status():
    health = {
        "status": "valid",
        "message": "Credencial válida",
        "detected": True,
        "metadata": {"email": "dev@test.com"},
    }
    account = build_agent_account_status(
        provider="claude",
        account_id="default",
        label="Claude (Padrão)",
        source="auto",
        health=health,
        manual_invite_url="https://claude.ai/invite/test",
    )

    assert account["id"] == "default"
    assert account["label"] == "Claude (Padrão)"
    assert account["provider"] == "claude"
    assert account["source"] == "auto"
    assert account["health"] == health

    # Native window checks
    assert account["native_window"]["type"] == "5h"
    assert account["native_window"]["usage_percentage"] == 0.0
    assert "release_time" in account["native_window"]
    assert "seconds_remaining" in account["native_window"]

    # Weekly window checks
    assert "total_tokens_or_turns" in account["weekly_window"]
    assert "cycle_reset_time" in account["weekly_window"]

    # Invites checks
    assert account["free_trial_invites"]["available_count"] == 0
    assert account["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/test"


def test_validate_status_contract():
    valid_contract = build_empty_status_contract()
    assert validate_status_contract(valid_contract) is True

    # Invalid contracts
    assert validate_status_contract({}) is False
    assert validate_status_contract({"version": 2}) is False
    assert validate_status_contract({"version": 1, "last_updated": "2026-10-20"}) is False
