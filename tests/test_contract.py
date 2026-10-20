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
    assert account["weekly_window"]["usage_percentage"] == 0.0
    assert "total_capacity" in account["weekly_window"]
    assert "available_capacity" in account["weekly_window"]

    # Invites checks
    assert account["free_trial_invites"]["available_count"] == 0
    assert account["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/test"


def test_build_agent_account_status_with_weekly_window():
    weekly = {
        "usage_percentage": 42.5,
        "total_capacity": 300,
        "available_capacity": 172,
        "used_capacity": 128,
        "cycle_reset_time": "2026-10-25T12:00:00Z",
        "seconds_remaining": 400000,
    }
    account = build_agent_account_status(
        provider="codex",
        account_id="dev",
        label="Codex Dev",
        source="manual",
        health={"status": "valid"},
        weekly_window=weekly,
    )
    assert account["weekly_window"]["usage_percentage"] == 42.5
    assert account["weekly_window"]["total_capacity"] == 300
    assert account["weekly_window"]["available_capacity"] == 172
    assert account["weekly_window"]["used_capacity"] == 128


def test_validate_status_contract():
    valid_contract = build_empty_status_contract()
    assert validate_status_contract(valid_contract) is True

    # Account with valid weekly window
    contract_with_account = build_empty_status_contract()
    contract_with_account["agents"]["claude"]["accounts"].append(
        build_agent_account_status(
            provider="claude",
            account_id="claude-1",
            label="Claude 1",
            source="manual",
            health={"status": "valid"},
            weekly_window={"usage_percentage": 50.0, "total_capacity": 200, "available_capacity": 100},
        )
    )
    assert validate_status_contract(contract_with_account) is True

    # Invalid weekly window usage_percentage
    invalid_contract = build_empty_status_contract()
    acc = build_agent_account_status(
        provider="claude",
        account_id="claude-1",
        label="Claude 1",
        source="manual",
        health={"status": "valid"},
    )
    acc["weekly_window"]["usage_percentage"] = "invalid_string"
    invalid_contract["agents"]["claude"]["accounts"].append(acc)
    assert validate_status_contract(invalid_contract) is False

    # Invalid contracts
    assert validate_status_contract({}) is False
    assert validate_status_contract({"version": 2}) is False
    assert validate_status_contract({"version": 1, "last_updated": "2026-10-20"}) is False
