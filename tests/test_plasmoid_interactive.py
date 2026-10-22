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

    # Essential methods and properties for deletion, renaming, and addition
    assert "getAccountsList" in content
    assert "requestDeleteAccount" in content
    assert "confirmDelete" in content
    assert "requestRenameAccount" in content
    assert "confirmRename" in content
    assert "addAccount" in content
    assert "captureCurrentAccount" in content
    assert "interactiveLoginAccount" in content
    assert "getDefaultPath" in content
    assert "clearAddAccountForm" in content
    assert "buildCollectorCommand" in content
    assert "--remove-account" in content
    assert "--rename-account" in content
    assert "--add-account" in content
    assert "--capture-current" in content
    assert "--interactive-login" in content

    # UI Elements: trash/delete icon, edit icon, dialogs, inline message, add form
    assert "delete" in content or "trash-empty" in content
    assert "document-edit" in content
    assert "renameAccountBtn" in content
    assert "confirmDialog" in content or "Dialog" in content
    assert "renameDialog" in content
    assert "renameAccountField" in content
    assert "InlineMessage" in content
    assert "statusMessage" in content
    assert "errorMessage" in content
    assert "isDeleting" in content
    assert "isRenaming" in content
    assert "isAdding" in content
    assert "isCapturing" in content
    assert "isInteractiveLogin" in content
    assert "isAddFormExpanded" in content
    assert "isAdvancedExpanded" in content


def test_config_general_gui_add_account_form_elements():
    """Verify that configGeneral.qml contains all required controls for adding, capturing and logging in."""
    config_general_path = UI_DIR / "configGeneral.qml"
    content = config_general_path.read_text(encoding="utf-8")

    # 1. Expandable section "Add New Account"
    assert "Add New Account" in content
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
    assert "Capture Current CLI Login" in content
    assert "captureCurrentAccount" in content

    assert "interactiveLoginAccountBtn" in content
    assert "Log In in the Terminal..." in content
    assert "interactiveLoginAccount" in content

    # 5. Collapsible Advanced Options Section (Manual Configuration)
    assert "Advanced Options (Manual Setup)" in content
    assert "toggleAdvancedBtn" in content
    assert "isAdvancedExpanded" in content

    # 6. Manual Path and Default button
    assert "credentialPathField" in content
    assert "useDefaultPathBtn" in content
    assert "Use Default Path" in content
    assert "~/.claude" in content
    assert "~/.codex" in content
    assert "~/.gemini" in content

    # 7. Optional invite URL TextField
    assert "inviteUrlField" in content
    assert "https://... (optional)" in content

    # 8. Save Account button and Clear button
    assert "saveAccountBtn" in content
    assert "Save Manually" in content
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
    full = (UI_DIR / "FullRepresentation.qml").read_text(encoding="utf-8")  # executor e clipboard únicos do popup

    # Clipboard function and utilities
    assert "copyToClipboard" in content and "copyText" in content
    assert "wl-copy" in full and "xclip" in full and "wl-copy" not in content

    # Visual feedback
    assert "copiedFeedback" in content
    assert "Copied!" in content
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
    assert "sucesso" in res.stdout.lower() or "removed" in res.stdout.lower()

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


# a resolução do comando do coletor no shell é testada com HOME falso em test_plasmoid_popup.py (test_collector_command_resolution_in_shell)


def test_account_card_weekly_meter_reactive_bindings():
    """O card reage ao relógio do popup (contagem ao vivo) e as duas janelas vêm do mesmo modelo."""
    content = (UI_DIR / "AccountCard.qml").read_text(encoding="utf-8")
    model = (UI_DIR / "NotchModel.js").read_text(encoding="utf-8")
    prefs = (UI_DIR / "ViewPrefs.js").read_text(encoding="utf-8")

    assert "nowMs" in content and "windowView" in content and "nativeView" in content and "weeklyView" in content
    assert "usage_percentage" in model and "tokens_used" in model
    assert "function countdown" in prefs and "function dateText" in prefs and "function shownPct" in prefs
    assert "nativeRow" in content and "weeklyRow" in content
    assert "countdownTimer" not in content  # o único relógio de 1 s é o do popup (FullRepresentation), só com ele aberto


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
    assert "provider: (providerComboBox.currentText || \"\").toLowerCase()" in content  # logo do provedor selecionado


def test_gui_capture_and_login_shell_injection_resilience(tmp_path: Path):
    """Verify that captureCurrentAccount and interactiveLoginAccount command formatting is safe."""
    config_general_path = UI_DIR / "configGeneral.qml"
    content = config_general_path.read_text(encoding="utf-8")

    # Verify captureCurrentAccount uses shellQuote for all parts
    capture_func_start = content.find("function captureCurrentAccount()")
    assert capture_func_start != -1
    capture_func_end = content.find("}", content.find("captureDataSource.connectSource", capture_func_start))
    capture_code = content[capture_func_start:capture_func_end]

    assert 'shellQuote("--capture-current")' in capture_code
    assert 'shellQuote(prov)' in capture_code
    assert 'shellQuote("--name")' in capture_code
    assert 'shellQuote(label)' in capture_code
    assert 'shellQuote("--status")' in capture_code

    # Verify interactiveLoginAccount uses shellQuote for all parts
    login_func_start = content.find("function interactiveLoginAccount()")
    assert login_func_start != -1
    login_func_end = content.find("}", content.find("interactiveLoginDataSource.connectSource", login_func_start))
    login_code = content[login_func_start:login_func_end]

    assert 'shellQuote("--interactive-login")' in login_code
    assert 'shellQuote(prov)' in login_code
    assert 'shellQuote("--name")' in login_code
    assert 'shellQuote(label)' in login_code
    assert 'shellQuote("--status")' in login_code

    # Test malicious command injection simulation for both
    pwned_marker = tmp_path / "pwned_interactive.txt"
    malicious_inputs = [
        f"hack'; touch {pwned_marker}; echo '",
        f'hack"$(touch {pwned_marker})"',
        f"hack`touch {pwned_marker}`",
        f"hack && touch {pwned_marker}",
    ]

    for evil_input in malicious_inputs:
        safe_quoted = "'" + evil_input.replace("'", "'\\''") + "'"
        cmd = f"bash -c 'for a in \"$@\"; do :; done' _ --capture-current {safe_quoted} --status"
        subprocess.run(cmd, shell=True, check=True)
        assert not pwned_marker.exists(), f"Vulnerability detected with payload: {evil_input}"


def test_config_general_qml_confirm_dialog_clean_layout_and_no_conflicting_standard_buttons():
    """Verify confirmDialog avoids conflicting standardButtons and has proper layout for custom action buttons."""
    config_general_path = UI_DIR / "configGeneral.qml"
    content = config_general_path.read_text(encoding="utf-8")

    # 1. Locate confirmDialog definition
    dialog_start = content.find("id: confirmDialog")
    assert dialog_start != -1, "confirmDialog definition not found in configGeneral.qml"

    dialog_end = content.find("\n    }", dialog_start)
    assert dialog_end != -1, "End of confirmDialog block not found"
    dialog_block = content[dialog_start:dialog_end]

    # 2. Verify no standardButtons are defined (prevents duplicate Cancel button overlap in Breeze theme)
    assert "standardButtons" not in dialog_block, (
        "confirmDialog must not define standardButtons (standardButtons: QQC2.Dialog.Cancel causes "
        "duplicate Cancel button collision in KDE Plasma 6 Breeze)"
    )

    # 3. Verify custom action buttons exist and are wired correctly
    assert "PlasmaComponents3.Button" in dialog_block
    assert "Cancel" in dialog_block
    assert "Remove Account" in dialog_block
    assert "confirmDialog.close()" in dialog_block
    assert "configRoot.confirmDelete()" in dialog_block

    # 4. Verify proper spacing and layout structure for clean Breeze presentation
    assert "ColumnLayout" in dialog_block
    assert "Kirigami.Units.largeSpacing" in dialog_block
    assert "RowLayout" in dialog_block
    assert "Qt.AlignRight" in dialog_block
    assert "Kirigami.Units.smallSpacing" in dialog_block


def test_config_general_qml_rename_dialog_clean_layout_and_no_conflicting_standard_buttons(tmp_path: Path):
    """Verify renameDialog avoids conflicting standardButtons, validates inputs, and executes safely."""
    config_general_path = UI_DIR / "configGeneral.qml"
    content = config_general_path.read_text(encoding="utf-8")

    # 1. Locate renameDialog definition
    dialog_start = content.find("id: renameDialog")
    assert dialog_start != -1, "renameDialog definition not found in configGeneral.qml"

    dialog_end = content.find("\n    }", dialog_start)
    assert dialog_end != -1, "End of renameDialog block not found"
    dialog_block = content[dialog_start:dialog_end]

    # 2. Verify no standardButtons are defined (prevents collision in KDE Plasma 6 Breeze)
    assert "standardButtons" not in dialog_block, (
        "renameDialog must not define standardButtons (prevents duplicate Cancel button collision in KDE Plasma 6 Breeze)"
    )

    # 3. Verify TextField and custom action buttons
    assert "renameAccountField" in dialog_block
    assert "QQC2.TextField" in dialog_block
    assert "PlasmaComponents3.Button" in dialog_block
    assert "Cancel" in dialog_block
    assert "Save" in dialog_block
    assert "saveRenameButton" in dialog_block
    assert "highlighted: true" in dialog_block
    assert "renameDialog.close()" in dialog_block
    assert "configRoot.confirmRename()" in dialog_block

    # 4. Verify GUI validation: does not allow saving if input is empty
    assert 'trim().length > 0' in dialog_block, "Save button should be disabled if field is empty"

    # 5. Verify confirmRename function formatting and shell injection resilience
    rename_func_start = content.find("function confirmRename()")
    assert rename_func_start != -1
    rename_func_end = content.find("}", content.find("renameDataSource.connectSource", rename_func_start))
    rename_code = content[rename_func_start:rename_func_end]

    assert 'shellQuote("--rename-account")' in rename_code
    assert 'shellQuote(provClean)' in rename_code
    assert 'shellQuote(acc.id)' in rename_code
    assert 'shellQuote("--label")' in rename_code
    assert 'shellQuote(newName)' in rename_code
    assert 'shellQuote("--status")' in rename_code

    # 6. Test shell injection safety
    pwned_marker = tmp_path / "pwned_rename.txt"
    malicious_inputs = [
        f"hack'; touch {pwned_marker}; echo '",
        f'hack"$(touch {pwned_marker})"',
        f"hack`touch {pwned_marker}`",
        f"hack && touch {pwned_marker}",
    ]

    for evil_input in malicious_inputs:
        safe_quoted = "'" + evil_input.replace("'", "'\\''") + "'"
        cmd = f"bash -c 'for a in \"$@\"; do :; done' _ --rename-account claude {safe_quoted} --label {safe_quoted} --status"
        subprocess.run(cmd, shell=True, check=True)
        assert not pwned_marker.exists(), f"Vulnerability detected with payload: {evil_input}"


def test_account_card_active_cli_badge():
    """Verify that AccountCard.qml contains the active CLI badge reading accountData.isActive."""
    card_path = UI_DIR / "AccountCard.qml"
    content = card_path.read_text(encoding="utf-8")

    # 1. Active property reading accountData.isActive
    assert "accountData.isActive" in content
    assert "isActive" in content

    # 2. Visual badge [✓ Active in the CLI]
    assert "activeCliBadge" in content
    assert "✓ Active in the CLI" in content
    assert "visible: cardRoot.isActive" in content
    assert "Kirigami.Theme.highlightColor" in content


def test_account_card_switch_account_button_and_contracts():
    """Verify that AccountCard.qml contains switch button, DataSource, and reactive updating."""
    card_path = UI_DIR / "AccountCard.qml"
    content = card_path.read_text(encoding="utf-8")

    # 1. Switch button with lightning icon/text
    assert "switchAccountButton" in content
    assert "⚡ Activate on System" in content
    assert "Activating..." in content

    # 2. Display condition: inactive accounts with valid health
    assert "!cardRoot.isActive" in content
    assert '"valid"' in content

    # 3. Busy and disabled state
    assert "isSwitching" in content
    assert "enabled: !cardRoot.isSwitching" in content

    # 4. Execução assíncrona pelo executor único do popup (sem DataSource por card)
    assert "runCollector" in content and "DataSource" not in content
    assert "switchAccount" in content
    assert "--switch-account" in content
    assert "--status" in content

    # 5. Immediate UI update notification on success
    assert "accountSwitched" in content
    assert "statusData" in content


def test_account_card_switch_account_shell_injection_resilience(tmp_path: Path):
    """Verify that AccountCard switchAccount command formatting with shellQuote prevents injection."""
    card_path = UI_DIR / "AccountCard.qml"
    content = card_path.read_text(encoding="utf-8")

    # Locate switchAccount function
    func_start = content.find("function switchAccount()")
    assert func_start != -1, "switchAccount function not found in AccountCard.qml"
    func_end = content.find("}", content.find("cardRoot.runCollector(", func_start))
    assert func_end != -1
    func_code = content[func_start:func_end]

    # Verify shellQuote is applied to all positional arguments
    assert 'Collector.shellQuote("--switch-account")' in func_code
    assert 'Collector.shellQuote(provClean)' in func_code
    assert 'Collector.shellQuote(accId)' in func_code
    assert 'Collector.shellQuote("--status")' in func_code

    # Test malicious command injection simulation
    pwned_marker = tmp_path / "pwned_switch.txt"
    malicious_inputs = [
        f"hack'; touch {pwned_marker}; echo '",
        f'hack"$(touch {pwned_marker})"',
        f"hack`touch {pwned_marker}`",
        f"hack && touch {pwned_marker}",
    ]

    for evil_input in malicious_inputs:
        safe_quoted = "'" + evil_input.replace("'", "'\\''") + "'"
        cmd = f"bash -c 'for a in \"$@\"; do :; done' _ --switch-account claude {safe_quoted} --status"
        subprocess.run(cmd, shell=True, check=True)
        assert not pwned_marker.exists(), f"Vulnerability detected with payload: {evil_input}"


@pytest.mark.skipif(shutil.which("qml6") is None, reason="qml6 binary not available")
def test_account_card_qml_syntax_validity():
    """Verify that AccountCard.qml parses cleanly with qml6."""
    card_path = UI_DIR / "AccountCard.qml"
    res = subprocess.run(
        ["qml6", "-I", str(UI_DIR.resolve()), "--quit-after", "200", str(card_path.resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"qml6 failed for AccountCard.qml: {res.stderr}"


def test_full_representation_wires_plasmoid_item_to_account_card():
    """Verify that FullRepresentation passes plasmoidItem and connects onAccountSwitched."""
    full_path = UI_DIR / "FullRepresentation.qml"
    content = full_path.read_text(encoding="utf-8")

    assert "plasmoidItem: fullRoot.plasmoidItem" in content
    assert "onAccountSwitched:" in content
    assert "loadStatus" in content


def test_main_qml_has_no_duplicate_switch_account():
    """AccountCard.qml is the only switch path; main.qml must not duplicate it (ADR-0008)."""
    main_path = UI_DIR / "main.qml"
    content = main_path.read_text(encoding="utf-8")

    assert "function switchAccount" not in content
    assert "--switch-account" not in content
    assert "shellQuote" in content
    assert "buildCollectorCommand" in content





def test_hover_open_option_and_wiring():
    """Ticket 34: opcao hoverOpen (main.xml + configGeneral) e ligacoes de hover/clique/Escape."""
    root = ET.parse(CONFIG_DIR / "main.xml").getroot()
    entries = {e.attrib["name"]: e for e in root.iter() if e.tag.endswith("entry")}
    assert entries["hoverOpen"].attrib["type"] == "Bool"
    assert entries["hoverOpen"].find("{*}default").text == "true"
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    assert "property bool cfg_hoverOpen" in cfg and "configRoot.cfg_hoverOpen = checked" in cfg
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    assert "toolTipTextFormat: Text.PlainText" in main and "hideOnWindowDeactivate: !pinned" in main
    compact = (UI_DIR / "CompactRepresentation.qml").read_text(encoding="utf-8")
    assert "setPillHovered(containsMouse)" in compact and "pillClicked(compactRoot.providerAt(mouse.x, mouse.y))" in compact
    assert "Keys.onEscapePressed" in compact
    full = (UI_DIR / "FullRepresentation.qml").read_text(encoding="utf-8")
    assert "HoverHandler" in full and "setPopupHovered(hovered)" in full
    assert "hideOnWindowDeactivate: !pinned && !pillHovered" in main and "openedByHover" in main
    assert "Component.onDestruction" in compact and "forceActiveFocus" in full
