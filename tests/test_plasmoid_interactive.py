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
    """Verify that configGeneral.qml contains account management, addition, capture and deletion bindings."""
    config_general_path = UI_DIR / "configGeneral.qml"
    assert config_general_path.is_file(), "contents/ui/configGeneral.qml must exist"

    content = config_general_path.read_text(encoding="utf-8")

    # Essential methods and properties for deletion and addition
    assert "getAccountsList" in content
    assert "requestDeleteAccount" in content
    assert "confirmDelete" in content
    assert "addAccount" in content
    assert "captureCurrentAccount" in content
    assert "interactiveLoginAccount" in content
    assert "getDefaultPath" in content
    assert "clearAddAccountForm" in content
    assert "buildCollectorCommand" in content
    assert "--remove-account" in content
    assert "--add-account" in content
    assert "--capture-current" in content
    assert "--interactive-login" in content

    # UI Elements: trash/delete icon, dialog, inline message, add form
    assert "delete" in content or "trash-empty" in content
    assert "confirmDialog" in content or "Dialog" in content
    assert "InlineMessage" in content
    assert "statusMessage" in content
    assert "errorMessage" in content
    assert "isAdding" in content
    assert "isCapturing" in content
    assert "isInteractiveLogin" in content
    assert "isAddFormExpanded" in content
    assert "isAdvancedExpanded" in content


def test_config_general_gui_add_account_form_elements():
    """Verify that configGeneral.qml contains all required controls for adding, capturing and logging in."""
    config_general_path = UI_DIR / "configGeneral.qml"
    content = config_general_path.read_text(encoding="utf-8")

    # 1. Expandable section "+ Adicionar Nova Conta"
    assert "+ Adicionar Nova Conta" in content
    assert "addAccountSection" in content
    assert "toggleAddFormBtn" in content
    assert "isAddFormExpanded" in content

    # 2. Provider ComboBox with Claude, Codex, Gemini and getProviderColor
    assert "providerComboBox" in content
    assert "getProviderColor" in content
    assert "Claude" in content and "Codex" in content and "Gemini" in content

    # 3. Label/Nickname TextField
    assert "accountNameField" in content

    # 4. Quick Action Buttons: Capture Current CLI Login and Interactive Terminal Login
    assert "captureCurrentAccountBtn" in content
    assert "Capturar Login Atual do CLI" in content
    assert "captureCurrentAccount" in content

    assert "interactiveLoginAccountBtn" in content
    assert "Fazer Login no Terminal..." in content
    assert "interactiveLoginAccount" in content

    # 5. Collapsible Advanced Options Section (Manual Configuration)
    assert "Opções Avançadas (Configuração Manual)" in content
    assert "toggleAdvancedBtn" in content
    assert "isAdvancedExpanded" in content

    # 6. Manual Path and Default button
    assert "credentialPathField" in content
    assert "useDefaultPathBtn" in content
    assert "Usar Caminho Padrão" in content
    assert "~/.claude" in content
    assert "~/.codex" in content
    assert "~/.gemini" in content

    # 7. Optional invite URL TextField
    assert "inviteUrlField" in content
    assert "https://... (opcional)" in content

    # 8. Save Account button and Clear button
    assert "saveAccountBtn" in content
    assert "Salvar Manualmente" in content
    assert "document-save" in content or "list-add" in content
    assert "clearFormBtn" in content

    # 9. Safe execution and DataSource bindings
    assert "additionDataSource" in content
    assert "captureDataSource" in content
    assert "interactiveLoginDataSource" in content
    assert "shellQuote" in content
    assert "--provider" in content
    assert "--label" in content
    assert "--credential-path" in content
    assert "--invite-url" in content
    assert "--status" in content


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


def test_simulated_gui_add_account_invocation(tmp_path: Path):
    """Simulate Plasmoid GUI add-account invocation through collector CLI."""
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"
    dummy_cred_dir = tmp_path / "custom_claude"
    dummy_cred_dir.mkdir(parents=True, exist_ok=True)
    (dummy_cred_dir / ".credentials.json").write_text("{}", encoding="utf-8")

    initial_config = {
        "version": "1.0",
        "agents": {
            "claude": {
                "accounts": [
                    {
                        "id": "claude-existing",
                        "label": "Claude Pessoal",
                        "source": "manual",
                        "session_token": "sk-111",
                    }
                ]
            }
        },
    }
    save_config(initial_config, config_path)
    collect_and_save(config_path=config_path, cache_path=cache_path)

    # Simulate GUI triggering account addition with --status
    cmd = [
        sys.executable,
        "-m",
        "ai_usage_collector.cli",
        "--add-account",
        "--provider",
        "claude",
        "--label",
        "Claude Trabalho",
        "--credential-path",
        str(dummy_cred_dir),
        "--invite-url",
        "https://claude.ai/invite/demo123",
        "--config-path",
        str(config_path),
        "--cache-path",
        str(cache_path),
        "--status",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Add account failed: {res.stderr}"
    assert "adicionada com sucesso" in res.stdout

    # Verify config.json was updated with permissions 0600
    assert config_path.is_file()
    assert oct(config_path.stat().st_mode & 0o777) == oct(0o600)
    with open(config_path, "r", encoding="utf-8") as f:
        updated_config = json.load(f)

    claude_accounts = updated_config["agents"]["claude"]["accounts"]
    assert len(claude_accounts) == 2
    labels = [acc["label"] for acc in claude_accounts]
    assert "Claude Trabalho" in labels
    assert "Claude Pessoal" in labels

    # Verify new account properties
    new_acc = [acc for acc in claude_accounts if acc["label"] == "Claude Trabalho"][0]
    assert new_acc["credential_path"] == str(dummy_cred_dir)
    assert new_acc["manual_invite_url"] == "https://claude.ai/invite/demo123"

    # Verify status.json was immediately updated and valid
    with open(cache_path, "r", encoding="utf-8") as f:
        status_cache = json.load(f)
    assert validate_status_contract(status_cache) is True
    cached_claude_accs = status_cache["agents"]["claude"]["accounts"]
    assert len(cached_claude_accs) == 2
    cached_new_acc = [acc for acc in cached_claude_accs if acc["id"] == new_acc["id"]][0]
    assert cached_new_acc["free_trial_invites"]["invite_url"] == "https://claude.ai/invite/demo123"


def test_gui_add_account_shell_injection_resilience(tmp_path: Path):
    """Verify that positional argument construction with shellQuote prevents shell injection."""
    pwned_marker = tmp_path / "pwned_marker.txt"
    malicious_inputs = [
        f"Label'; touch {pwned_marker}; echo '",
        f'Label"$(touch {pwned_marker})"',
        f'Label`touch {pwned_marker}`',
        f"Label || touch {pwned_marker}",
    ]

    for malicious_input in malicious_inputs:
        safe_quoted = "'" + malicious_input.replace("'", "'\\''") + "'"
        # Simulate buildCollectorCommand: bash -c '... "$@"' _ <quotedArgs>
        bash_cmd = (
            "bash -c 'for arg in \"$@\"; do printf \"%s\\n\" \"$arg\"; done' _ "
            + safe_quoted
        )
        res = subprocess.run(bash_cmd, shell=True, capture_output=True, text=True, check=True)
        # Verify the malicious command was NOT executed
        assert not pwned_marker.exists(), f"Shell injection vulnerability triggered by: {malicious_input}"
        # Verify argument was received exactly as literal string
        assert res.stdout.strip() == malicious_input


def test_config_general_qml_combobox_native_breeze_compliance():
    """Verify provider ComboBox uses native PlasmaComponents3 and avoids text-overlap bugs."""
    config_general_path = UI_DIR / "configGeneral.qml"
    content = config_general_path.read_text(encoding="utf-8")

    # 1. Native PlasmaComponents3 ComboBox
    assert "PlasmaComponents3.ComboBox" in content
    assert "providerComboBox" in content

    # 2. Extract providerComboBox block
    combo_start = content.find("PlasmaComponents3.ComboBox {")
    assert combo_start != -1, "PlasmaComponents3.ComboBox definition not found"
    combo_end = content.find("}", combo_start)
    assert combo_end != -1
    combo_block = content[combo_start:combo_end]

    # 3. Model defines all supported providers
    assert '"Claude"' in combo_block
    assert '"Codex"' in combo_block
    assert '"Gemini"' in combo_block

    # 4. No conflicting contentItem or custom Label overrides inside ComboBox
    # (prevents duplicate rendering/overlapping 'Claudede' bug under Breeze theme)
    assert "contentItem:" not in combo_block
    assert "QQC2.Label {" not in combo_block

    # 5. Visual color indicator is maintained safely outside ComboBox layout
    assert "providerIndicator" in content
    assert "configRoot.getProviderColor(providerComboBox.currentText)" in content




