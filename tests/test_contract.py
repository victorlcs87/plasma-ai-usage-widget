from ai_usage_collector.contract import (
    build_empty_status_contract,
    build_agent_account_status,
    validate_status_contract,
    AGENT_NATIVE_WINDOWS,
    parse_window_seconds,
    window_type_from_seconds,
)


def test_agent_native_windows_definition():
    assert AGENT_NATIVE_WINDOWS["claude"] == "5h"
    assert AGENT_NATIVE_WINDOWS["codex"] == "3h"
    assert AGENT_NATIVE_WINDOWS["gemini"] == "daily"


def test_build_empty_status_contract():
    contract = build_empty_status_contract()
    assert contract["version"] == 4
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


def test_build_agent_account_status_is_active():
    acc_inactive = build_agent_account_status(
        provider="claude",
        account_id="claude-1",
        label="Claude 1",
        source="manual",
        health={"status": "valid"},
        is_active=False,
    )
    assert acc_inactive["isActive"] is False

    acc_active = build_agent_account_status(
        provider="claude",
        account_id="claude-2",
        label="Claude 2",
        source="manual",
        health={"status": "valid"},
        is_active=True,
    )
    assert acc_active["isActive"] is True


def test_validate_status_contract_is_active():
    contract = build_empty_status_contract()
    acc = build_agent_account_status(
        provider="codex",
        account_id="codex-1",
        label="Codex 1",
        source="manual",
        health={"status": "valid"},
        is_active=True,
    )
    contract["agents"]["codex"]["accounts"].append(acc)
    assert validate_status_contract(contract) is True

    # If isActive is not a bool, validation should fail
    acc["isActive"] = "not_a_bool"
    assert validate_status_contract(contract) is False


def test_window_duration_and_elapsed_fraction_fields():
    acc = build_agent_account_status(
        provider="codex",
        account_id="c1",
        label="C1",
        source="auto",
        health={"status": "valid"},
        native_window={"window_seconds": 18000, "seconds_remaining": 4500},
        weekly_window={"window_seconds": 604800, "seconds_remaining": 151200},
    )
    assert acc["native_window"]["window_seconds"] == 18000
    assert acc["native_window"]["elapsed_fraction"] == 0.75
    assert acc["weekly_window"]["window_seconds"] == 604800
    assert acc["weekly_window"]["elapsed_fraction"] == 0.75


def test_elapsed_fraction_unknown_or_clamped():
    acc = build_agent_account_status(
        provider="claude",
        account_id="c1",
        label="C1",
        source="auto",
        health={"status": "valid"},
        native_window={"window_seconds": 18000, "seconds_remaining": None},
        weekly_window={"window_seconds": 604800, "seconds_remaining": 999999},
    )
    assert acc["native_window"]["elapsed_fraction"] is None
    assert acc["weekly_window"]["elapsed_fraction"] == 0.0
    empty = build_agent_account_status(
        provider="gemini", account_id="g", label="G", source="auto", health={"status": "valid"}
    )
    assert empty["native_window"]["window_seconds"] is None
    assert empty["native_window"]["elapsed_fraction"] is None
    assert empty["weekly_window"]["elapsed_fraction"] is None


def test_older_contract_versions_remain_valid():
    status = build_empty_status_contract()
    for version in (1, 2, 3, 4):
        status["version"] = version
        assert validate_status_contract(status) is True
    status["version"] = 99
    assert validate_status_contract(status) is False


def test_parse_window_seconds_and_type():
    assert parse_window_seconds(18000) == 18000
    assert parse_window_seconds("18000s") == 18000
    assert parse_window_seconds("5h") == 18000
    assert parse_window_seconds("7d") == 604800
    assert parse_window_seconds("weekly") == 604800
    assert parse_window_seconds("daily") == 86400
    assert parse_window_seconds(0) is None
    assert parse_window_seconds(True) is None
    assert parse_window_seconds("bogus") is None
    assert parse_window_seconds(None) is None
    assert window_type_from_seconds(18000) == "5h"
    assert window_type_from_seconds(10800) == "3h"
    assert window_type_from_seconds(86400) == "daily"
    assert window_type_from_seconds(5400) == "90m"


def test_parse_window_seconds_rejects_hostile_values():
    # M1: valores infinitos/enormes da API nao podem derrubar a coleta
    assert parse_window_seconds(float("inf")) is None
    assert parse_window_seconds(float("nan")) is None
    assert parse_window_seconds(10**400) is None
    assert parse_window_seconds("9" * 400 + "h") is None
    assert parse_window_seconds("9" * 400) is None
    assert parse_window_seconds(400 * 86400) is None  # acima do teto de 1 ano
    # B2
    assert parse_window_seconds(0.5) is None
    assert parse_window_seconds("18000") == 18000
    assert parse_window_seconds("٥h") is None  # digito arabe-indico


def test_window_type_from_seconds_weekly_and_short():
    # B1
    assert window_type_from_seconds(604800) == "7d"
    assert window_type_from_seconds(30) == "30s"
    assert window_type_from_seconds(90) == "90s"



def test_orphan_profiles_must_be_list_of_dicts():  # B4
    c = build_empty_status_contract()
    c["orphan_profiles"] = [{"id": "x"}]
    assert validate_status_contract(c)
    c["orphan_profiles"] = "x"
    assert not validate_status_contract(c)
    c["orphan_profiles"] = ["x"]
    assert not validate_status_contract(c)
