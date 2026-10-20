"""Tests for Plasma 6 Plasmoid packaging, metadata integrity, and QML contract compliance."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ai_usage_collector.contract import (
    build_agent_account_status,
    build_empty_status_contract,
    validate_status_contract,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PLASMOID_DIR = REPO_ROOT / "plasmoid"
METADATA_PATH = PLASMOID_DIR / "metadata.json"
UI_DIR = PLASMOID_DIR / "contents" / "ui"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-plasmoid.sh"


def test_plasmoid_directory_structure():
    """Verify that all required files and directories for the Plasmoid exist."""
    assert PLASMOID_DIR.is_dir(), "plasmoid/ directory must exist"
    assert METADATA_PATH.is_file(), "plasmoid/metadata.json must exist"
    assert UI_DIR.is_dir(), "plasmoid/contents/ui/ directory must exist"

    expected_qml_files = [
        "main.qml",
        "CompactRepresentation.qml",
        "FullRepresentation.qml",
        "AccountCard.qml",
        "UsageDetails.qml",
        "TokenHistory.qml",
        "configGeneral.qml",
    ]
    for qml_file in expected_qml_files:
        path = UI_DIR / qml_file
        assert path.is_file(), f"Missing QML component: {qml_file}"
        assert path.stat().st_size > 0, f"QML component {qml_file} is empty"

    config_dir = PLASMOID_DIR / "contents" / "config"
    assert config_dir.is_dir(), "plasmoid/contents/config/ directory must exist"
    assert (config_dir / "main.xml").is_file(), "plasmoid/contents/config/main.xml must exist"
    assert (config_dir / "config.qml").is_file(), "plasmoid/contents/config/config.qml must exist"


def test_metadata_json_schema_and_plasma6_compliance():
    """Verify that metadata.json conforms to KDE Plasma 6 specification."""
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Plasma 6 root package structure
    assert meta.get("KPackageStructure") == "Plasma/Applet"
    assert meta.get("X-Plasma-API-Minimum-Version") == "6.0"

    plugin = meta.get("KPlugin")
    assert isinstance(plugin, dict), "KPlugin object must exist in metadata.json"
    assert plugin.get("Id") == "org.kde.plasma.aiusage"
    assert plugin.get("Name"), "KPlugin Name must be defined"
    assert plugin.get("Description"), "KPlugin Description must be defined"
    assert plugin.get("Icon"), "KPlugin Icon must be defined"
    assert plugin.get("Category") == "Utilities"
    assert plugin.get("License") == "MIT"
    assert plugin.get("Version") == "1.0.0"

    authors = plugin.get("Authors")
    assert isinstance(authors, list) and len(authors) > 0
    assert authors[0].get("Name")


@pytest.mark.skipif(shutil.which("kpackagetool6") is None, reason="kpackagetool6 not available")
def test_kpackagetool6_hash_validation():
    """Verify that kpackagetool6 validates package structure and generates SHA1 hash."""
    result = subprocess.run(
        ["kpackagetool6", "-t", "Plasma/Applet", "--hash", str(PLASMOID_DIR.resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"kpackagetool6 hash failed: {result.stderr}"
    assert "SHA1" in result.stdout or "hash" in result.stdout.lower()


def test_install_script_attributes_and_execution():
    """Verify scripts/install-plasmoid.sh is executable and runs cleanly."""
    assert INSTALL_SCRIPT.is_file(), "install-plasmoid.sh script must exist"
    assert os.access(INSTALL_SCRIPT, os.X_OK), "install-plasmoid.sh must have executable bit set"

    result = subprocess.run(
        [str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"install-plasmoid.sh failed: stdout={result.stdout}, stderr={result.stderr}"

    installed_dir = Path.home() / ".local" / "share" / "plasma" / "plasmoids" / "org.kde.plasma.aiusage"
    assert (installed_dir / "metadata.json").is_file()
    assert (installed_dir / "contents" / "ui" / "main.qml").is_file()


@pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")
def test_qml_components_syntax_validity():
    """Verify that standalone QML components parse without syntax errors using qml6."""
    components_to_check = [
        "AccountCard.qml",
        "UsageDetails.qml",
        "TokenHistory.qml",
        "CompactRepresentation.qml",
        "FullRepresentation.qml",
        "configGeneral.qml",
    ]
    for comp in components_to_check:
        comp_path = UI_DIR / comp
        res = subprocess.run(
            ["qml6", "-I", str(UI_DIR.resolve()), "--quit-after", "200", str(comp_path.resolve())],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"qml6 failed for {comp}: stdout={res.stdout}, stderr={res.stderr}"


def test_qml_contract_keys_compatibility():
    """Verify that keys consumed by QML components match the Python contract exactly."""
    payload = build_empty_status_contract()

    # Populate dummy accounts matching extractor outputs
    claude_acc = build_agent_account_status(
        provider="claude",
        account_id="claude-pro",
        label="Claude Pro",
        source="auto",
        health={"status": "valid", "message": "Ativa", "detected": True},
        native_window={
            "total_capacity": 45,
            "used_capacity": 13,
            "available_capacity": 32,
            "usage_percentage": 28.9,
            "release_time": "2026-10-20T17:10:32+00:00",
            "seconds_remaining": 11344,
        },
        weekly_window={
            "used_capacity": 11325,
            "cycle_reset_time": "2026-10-20T16:57:06+00:00",
            "seconds_remaining": 10538,
            "tokens_used": 1287473687,
        },
        free_trial_invites={
            "available_count": 2,
            "invite_url": "https://claude.ai/invite/test",
        },
    )
    payload["agents"]["claude"]["accounts"].append(claude_acc)

    assert validate_status_contract(payload) is True

    # Check that contract contains all keys needed by main.qml, CompactRepresentation.qml, FullRepresentation.qml, AccountCard.qml
    assert "version" in payload
    assert "last_updated" in payload
    assert "status" in payload
    assert "agents" in payload

    agent = payload["agents"]["claude"]
    assert "name" in agent
    assert "accounts" in agent
    assert len(agent["accounts"]) == 1

    acc = agent["accounts"][0]
    required_acc_keys = [
        "id", "name", "label", "provider", "source",
        "health", "native_window", "weekly_window", "free_trial_invites"
    ]
    for key in required_acc_keys:
        assert key in acc

    assert acc["health"]["status"] in ["valid", "session_expired", "not_configured", "error"]
    assert "message" in acc["health"]

    assert "type" in acc["native_window"]
    assert "total_capacity" in acc["native_window"]
    assert "used_capacity" in acc["native_window"]
    assert "available_capacity" in acc["native_window"]
    assert "usage_percentage" in acc["native_window"]
    assert "release_time" in acc["native_window"]
    assert "seconds_remaining" in acc["native_window"]

    assert "used_capacity" in acc["weekly_window"]
    assert "usage_percentage" in acc["weekly_window"]
    assert "tokens_used" in acc["weekly_window"]
    assert "cycle_reset_time" in acc["weekly_window"]
    assert "seconds_remaining" in acc["weekly_window"]

    assert "available_count" in acc["free_trial_invites"]
    assert "invite_url" in acc["free_trial_invites"]


def test_account_card_qml_symmetric_meters_and_clean_capacity():
    """Verify AccountCard.qml implements symmetric meters without raw message counts."""
    card_path = UI_DIR / "AccountCard.qml"
    assert card_path.is_file()
    content = card_path.read_text(encoding="utf-8")

    # 1. Raw message counters removed from primary capacity display
    assert "Capacidade:" not in content
    assert "msgs" not in content

    # 2. Symmetric Active Window Meter
    assert "Janela Ativa (5h)" in content
    assert "Janela Ativa (3h)" in content
    assert "Janela Diária" in content
    assert "nativeProgressBar" in content
    assert "liveSecondsRemaining" in content

    # 3. Symmetric Weekly Window Meter
    assert "Janela Semanal (7 dias)" in content
    assert "weeklyProgressBar" in content
    assert "weekly_window" in content
    assert "liveWeeklySecondsRemaining" in content
    assert "cycle_reset_time" in content

    # 4. Unified dynamic color thresholds (< 70%, 70-90%, > 90%)
    assert "Kirigami.Theme.positiveTextColor" in content
    assert "Kirigami.Theme.neutralTextColor" in content
    assert "Kirigami.Theme.negativeTextColor" in content
    assert "70" in content and "90" in content

    # 5. Free trial invite preservation
    assert "free_trial_invites" in content
    assert "copyToClipboard" in content
    assert "shellQuote" in content


def test_config_general_qml_add_account_form_packaging_and_controls():
    """Verify configGeneral.qml includes the complete add-account form controls and functions."""
    config_path = UI_DIR / "configGeneral.qml"
    assert config_path.is_file()
    content = config_path.read_text(encoding="utf-8")

    # Header and expandable container
    assert "+ Adicionar Nova Conta" in content
    assert "addAccountSection" in content
    assert "isAddFormExpanded" in content
    assert "toggleAddFormBtn" in content

    # Controls: provider ComboBox (native PlasmaComponents3), indicator, labels, textfields
    assert "providerComboBox" in content
    assert "PlasmaComponents3.ComboBox" in content
    assert "providerIndicator" in content
    assert "accountNameField" in content
    assert "captureCurrentAccountBtn" in content
    assert "interactiveLoginAccountBtn" in content
    assert "credentialPathField" in content
    assert "useDefaultPathBtn" in content
    assert "inviteUrlField" in content
    assert "saveAccountBtn" in content

    # Helper and action methods
    assert "getDefaultPath" in content
    assert "clearAddAccountForm" in content
    assert "addAccount" in content
    assert "captureCurrentAccount" in content
    assert "interactiveLoginAccount" in content
    assert "shellQuote" in content
    assert "buildCollectorCommand" in content
    assert "additionDataSource" in content
    assert "captureDataSource" in content
    assert "interactiveLoginDataSource" in content
    assert "--capture-current" in content
    assert "--interactive-login" in content




def test_account_card_shows_optional_token_history():
    """AccountCard usa TokenHistory e tolera a ausencia de token_history (contrato v1)."""
    card = (UI_DIR / "AccountCard.qml").read_text(encoding="utf-8")
    assert "TokenHistory {" in card
    assert "token_history ?? null" in card
    comp = (UI_DIR / "TokenHistory.qml").read_text(encoding="utf-8")
    for key in ["today", "week", "month", "daily_30d", "weekly_3m", "monthly_12m", "Repeater", "Rectangle"]:
        assert key in comp
    assert "visible: Boolean(history)" in comp
