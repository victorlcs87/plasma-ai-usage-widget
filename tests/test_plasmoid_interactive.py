"""Tests for Plasmoid interactive actions: On-demand refresh, Copy Invite, and Config GUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from ai_usage_collector.collector import collect_and_save
from ai_usage_collector.config import save_config
from ai_usage_collector.contract import validate_status_contract

REPO_ROOT = Path(__file__).resolve().parent.parent
PLASMOID_DIR = REPO_ROOT / "plasmoid"
CONTENTS_DIR = PLASMOID_DIR / "contents"
CONFIG_DIR = CONTENTS_DIR / "config"
UI_DIR = CONTENTS_DIR / "ui"


def test_config_xml_schema_and_integrity():
    """Verify that contents/config/main.xml is valid XML and defines KConfigXT schema."""
    main_xml_path = CONFIG_DIR / "main.xml"
    assert main_xml_path.is_file(), "contents/config/main.xml must exist"
    assert main_xml_path.stat().st_size > 0, "main.xml must not be empty"

    tree = ET.parse(main_xml_path)
    root = tree.getroot()

    # Verify root tag name and namespace
    assert "kcfg" in root.tag.lower()

    # Find General group
    groups = [elem for elem in root.iter() if elem.tag.endswith("group")]
    assert len(groups) >= 1
    general_group = groups[0]
    assert general_group.attrib.get("name") == "General"

    # Verify entries within group
    entries = {
        entry.attrib.get("name"): entry.attrib.get("type")
        for entry in general_group.findall("{*}entry") or general_group.findall("entry")
    }
    assert "autoRefreshOnExpand" in entries
    assert entries["autoRefreshOnExpand"] == "Bool"


def test_config_qml_registration():
    """Verify that contents/config/config.qml registers configGeneral.qml."""
    config_qml_path = CONFIG_DIR / "config.qml"
    assert config_qml_path.is_file(), "contents/config/config.qml must exist"

    content = config_qml_path.read_text(encoding="utf-8")
    assert "ConfigModel" in content
    assert "ConfigCategory" in content
    assert "configGeneral.qml" in content


def test_config_general_qml_structure_and_bindings():
    """Verify that configGeneral.qml contains account management and deletion bindings."""
    config_general_path = UI_DIR / "configGeneral.qml"
    assert config_general_path.is_file(), "contents/ui/configGeneral.qml must exist"

    content = config_general_path.read_text(encoding="utf-8")

    # Essential methods and properties
    assert "getAccountsList" in content
    assert "requestDeleteAccount" in content
    assert "confirmDelete" in content
    assert "buildCollectorCommand" in content
    assert "--remove-account" in content

    # UI Elements: trash/delete icon, dialog, inline message
    assert "delete" in content or "trash-empty" in content
    assert "confirmDialog" in content or "Dialog" in content
    assert "InlineMessage" in content
    assert "statusMessage" in content
    assert "errorMessage" in content


@pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")
def test_config_general_qml_syntax_validity():
    """Verify that configGeneral.qml parses cleanly with qml6."""
    config_general_path = UI_DIR / "configGeneral.qml"
    res = subprocess.run(
        ["qml6", "-I", str(UI_DIR.resolve()), "--quit-after", "200", str(config_general_path.resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"qml6 failed for configGeneral.qml: {res.stderr}"


def test_full_representation_refresh_button_and_animation():
    """Verify that FullRepresentation.qml contains refresh button, spinner, and timestamp."""
    full_path = UI_DIR / "FullRepresentation.qml"
    content = full_path.read_text(encoding="utf-8")

    # Refresh button with view-refresh icon
    assert "refreshButton" in content
    assert "view-refresh" in content
    assert "refreshCollector" in content

    # Loading/refreshing visual indicator
    assert "isRefreshing" in content
    assert "RotationAnimator" in content or "BusyIndicator" in content
    assert "refreshProgressBar" in content

    # Timestamp display
    assert "lastUpdatedFormatted" in content


def test_account_card_copy_invite_and_clipboard_actions():
    """Verify that AccountCard.qml supports clipboard copy with visual feedback."""
    card_path = UI_DIR / "AccountCard.qml"
    content = card_path.read_text(encoding="utf-8")

    # Clipboard function and utilities
    assert "copyToClipboard" in content
    assert "wl-copy" in content
    assert "xclip" in content

    # Visual feedback
    assert "copiedFeedback" in content
    assert "Copiado!" in content
    assert "copiedFeedbackTimer" in content


def test_simulated_on_demand_refresh_invocation(tmp_path: Path):
    """Simulate Plasmoid on-demand refresh invocation through collector CLI."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    initial_config = {
        "version": "1.0",
        "accounts": {
            "claude": [
                {
                    "id": "claude-test",
                    "label": "Claude Test Account",
                    "source": "manual",
                    "session_token": "sk-dummy-12345",
                    "invite_url": "https://claude.ai/invite/test12345",
                }
            ]
        },
    }
    save_config(initial_config, config_path)

    # Invoke collector via CLI with --refresh
    cmd = [
        sys.executable,
        "-m",
        "ai_usage_collector.cli",
        "--refresh",
        "--config-path",
        str(config_path),
        "--cache-path",
        str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Refresh failed: stderr={res.stderr}, stdout={res.stdout}"

    # Verify status.json was created and conforms to schema
    assert cache_path.is_file()
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert validate_status_contract(data) is True
    assert data["status"] == "ok"
    assert "claude" in data["agents"]
    assert len(data["agents"]["claude"]["accounts"]) == 1
    assert data["agents"]["claude"]["accounts"][0]["id"] == "claude-test"


def test_simulated_remove_account_from_widget(tmp_path: Path):
    """Simulate Plasmoid removal action via CLI '--remove-account'."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    initial_config = {
        "version": "1.0",
        "accounts": {
            "claude": [
                {
                    "id": "claude-primary",
                    "label": "Claude Primary",
                    "source": "manual",
                    "session_token": "sk-111",
                },
                {
                    "id": "claude-to-delete",
                    "label": "Claude Temporary",
                    "source": "manual",
                    "session_token": "sk-222",
                },
            ],
            "codex": [
                {
                    "id": "codex-main",
                    "label": "Codex Main",
                    "source": "manual",
                    "session_token": "sk-333",
                }
            ],
        },
    }
    save_config(initial_config, config_path)
    collect_and_save(config_path=config_path, cache_path=cache_path)

    # Initial check: 2 claude accounts in cache
    with open(cache_path, "r", encoding="utf-8") as f:
        initial_cache = json.load(f)
    assert len(initial_cache["agents"]["claude"]["accounts"]) == 2

    # Simulate GUI triggering account deletion
    cmd = [
        sys.executable,
        "-m",
        "ai_usage_collector.cli",
        "--remove-account",
        "claude",
        "claude-to-delete",
        "--config-path",
        str(config_path),
        "--cache-path",
        str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Removal failed: {res.stderr}"
    assert "sucesso" in res.stdout.lower() or "removida" in res.stdout.lower()

    # Verify account was removed from config.json
    with open(config_path, "r", encoding="utf-8") as f:
        updated_config = json.load(f)
    claude_ids = [acc["id"] for acc in updated_config["accounts"]["claude"]]
    assert "claude-to-delete" not in claude_ids
    assert "claude-primary" in claude_ids

    # Verify cache was immediately synchronized
    with open(cache_path, "r", encoding="utf-8") as f:
        updated_cache = json.load(f)
    updated_claude_ids = [acc["id"] for acc in updated_cache["agents"]["claude"]["accounts"]]
    assert "claude-to-delete" not in updated_claude_ids
    assert "claude-primary" in updated_claude_ids
    assert len(updated_cache["agents"]["claude"]["accounts"]) == 1


def test_clipboard_fallback_shell_safety():
    """Verify that invite URL escaping for wl-copy/xclip command is shell-safe."""
    test_urls = [
        "https://claude.ai/invite/code?ref=user&id=123",
        "https://codex.openai.com/trial#token=xyz!$%",
        "https://ai.google.dev/invites/abc'def'ghi",
        'https://example.com/test"$(echo pwned)"`id`$HOME',
    ]

    for url in test_urls:
        safe_quoted = "'" + url.replace("'", "'\\''") + "'"
        bash_cmd = (
            "bash -c 'if command -v wl-copy >/dev/null 2>&1; then printf \"%s\" \"$1\" | wl-copy; "
            "elif command -v xclip >/dev/null 2>&1; then printf \"%s\" \"$1\" | xclip -selection clipboard; "
            "else printf \"%s\" \"$1\"; fi' _ " + safe_quoted
        )
        res = subprocess.run(bash_cmd, shell=True, capture_output=True, text=True, check=True)
        assert res.stdout == url, f"URL alterada ou comando expandido indevidamente: {res.stdout!r} != {url!r}"



def test_main_qml_interactive_contracts():
    """Verify that main.qml declares required reactive properties and methods."""
    main_qml_path = UI_DIR / "main.qml"
    content = main_qml_path.read_text(encoding="utf-8")

    assert "isRefreshing" in content
    assert "buildCollectorCommand" in content
    assert "collectorDataSource" in content
    assert "refreshCollector" in content
    assert "removeAccount" in content
    assert "loadStatus" in content


def test_build_collector_command_resolution_in_shell():
    """Verify that the shell command construct in QML executes successfully."""
    venv_bin = REPO_ROOT / ".venv" / "bin" / "ai-usage-collector"
    assert venv_bin.is_file() and os.access(venv_bin, os.X_OK)

    args = "'--version'"
    bash_cmd = (
        f"bash -c 'if command -v ai-usage-collector >/dev/null 2>&1; then ai-usage-collector \"$@\"; "
        f"elif [ -x \"$HOME/.local/bin/ai-usage-collector\" ]; then \"$HOME/.local/bin/ai-usage-collector\" \"$@\"; "
        f"elif [ -x \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" ]; then \"$HOME/repositorios/plasma-ai-usage-widget/.venv/bin/ai-usage-collector\" \"$@\"; "
        f"else python3 -m ai_usage_collector \"$@\"; fi' _ {args}"
    )
    res = subprocess.run(["bash", "-c", bash_cmd], capture_output=True, text=True, check=False)
    assert res.returncode == 0
    assert "ai-usage-collector" in res.stdout


def test_account_card_weekly_meter_reactive_bindings():
    """Verify AccountCard.qml contains reactive countdowns, token formatters and weekly bindings."""
    card_path = UI_DIR / "AccountCard.qml"
    content = card_path.read_text(encoding="utf-8")

    # Verification of progress bars and bindings to percentage / 100.0
    assert "nativeProgressBar" in content
    assert "weeklyProgressBar" in content
    assert "/ 100.0" in content
    assert "usage_percentage" in content

    # Formatter functions for tokens, percentages and timestamps
    assert "formatPercentage" in content
    assert "formatNumber" in content
    assert "formatCountdown" in content
    assert "formatDateTime" in content
    assert "getUsageColor" in content

    # Symmetric layout elements
    assert "activeWindowTitleLabel" in content
    assert "activeWindowPercentageLabel" in content
    assert "weeklyWindowTitleLabel" in content
    assert "weeklyWindowPercentageLabel" in content


