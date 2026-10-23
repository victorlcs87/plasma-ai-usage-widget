"""Tests for Plasma 6 Plasmoid packaging, metadata integrity, and QML contract compliance."""

from __future__ import annotations

import json
import importlib.util
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

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
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package-release.sh"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

LOGO_PROVIDERS = ("claude", "codex", "gemini")


def test_provider_logos_are_clean_single_path_svgs_with_registered_source():
    """Um SVG por provedor de Presets.js: um só path, sem script/imagem/estilo; fonte e licença registradas."""
    presets = (UI_DIR / "Presets.js").read_text(encoding="utf-8")
    assert re.findall(r'key: "(\w+)", name:', presets) == list(LOGO_PROVIDERS)
    for p in LOGO_PROVIDERS:
        svg = (UI_DIR / f"logo-{p}.svg").read_text(encoding="utf-8")
        assert svg.count("<path") == 1 and svg.count("<") == 3  # <svg>, <path/>, </svg>
        assert not re.search(r"<script|<image|<style|href|onload|<foreignObject", svg, re.I)
    notes = (UI_DIR / "LOGOS.md").read_text(encoding="utf-8")
    assert "CC0" in notes and "simple-icons" in notes and "marcas registradas" in notes.lower()
    logo = (UI_DIR / "ProviderLogo.qml").read_text(encoding="utf-8")
    assert "Accessible.ignored: true" in logo and '"?"' in logo
    for p in LOGO_PROVIDERS:
        assert f'provider === "{p}"' in logo


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
    assert plugin.get("License") == "GPL-3.0-or-later"
    assert plugin.get("Version") == "1.1.1"

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
        "DualRing.qml",
        "PanelItem.qml",
        "LevelBars.qml",
        "SessionMark.qml",
        "ProviderLogo.qml",
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
        health={"status": "valid", "message": "Active", "detected": True},
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
    """O card mostra as duas janelas simétricas (via NotchModel.windowView), sem contagem crua de mensagens."""
    card_path = UI_DIR / "AccountCard.qml"
    assert card_path.is_file()
    content = card_path.read_text(encoding="utf-8")
    model = (UI_DIR / "NotchModel.js").read_text(encoding="utf-8")

    # 1. Raw message counters removed from primary capacity display
    assert "Capacidade:" not in content
    assert "msgs" not in content

    # 2. Janela Ativa/Semanal simétricas, com marca de tempo decorrido ao vivo e o relógio do popup
    assert "Active Window (5h)" in model and "Active Window (3h)" not in model  # duracao vem do provedor via %1
    assert "Active Window (%1)" in model and "Daily Window" in model and "Weekly Window (7 days)" in model
    assert "elapsed_fraction" in model and "cycle_reset_time" in model and "release_time" in model
    assert "nativeRow" in content and "weeklyRow" in content and "nowMs" in content and "weekly_window" in content

    # 3. Cor SÓ pelo nível do contrato: nada de limiares fixos 70/90 nem cores do tema por percentual
    assert "getUsageColor" not in content and "< 70" not in content and "<= 90" not in content
    assert "Kirigami.Theme.positiveTextColor" not in content and "Presets.levelColor" in content

    # 4. Free trial invite preservation
    assert "free_trial_invites" in content
    assert "copyToClipboard" in content
    assert "shellQuote" in content


def test_config_general_qml_add_account_form_packaging_and_controls():
    """Verify configGeneral.qml includes the complete add-account form controls and functions."""
    config_path = UI_DIR / "configGeneral.qml"
    assert config_path.is_file()
    content = config_path.read_text(encoding="utf-8")

    # Header and expandable container
    assert "Add New Account" in content
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


def test_cards_show_forecast_and_level_with_text_and_shapes():
    card = (UI_DIR / "AccountCard.qml").read_text(encoding="utf-8")
    row = (UI_DIR / "WindowRow.qml").read_text(encoding="utf-8")
    model = (UI_DIR / "NotchModel.js").read_text(encoding="utf-8")
    for needle in ("alert_level", "forecast", "Runs out in"):
        assert needle in model
    for needle in ("Text.PlainText", "levelWord", "levelMark", "forecast"):
        assert needle in row  # nível por palavra e forma, além da cor
    assert "Presets.levelTextColor" in row and "#" not in row.split("levelTextColor")[1].split("\n")[0]  # cor vem do nível, nunca hex fixo
    assert "forecast" in card.lower() or "windowView" in card


def test_config_general_exposes_alert_mode_and_thresholds():
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    for needle in ("--set-alert-config", "--alert-mode", "--alert-warning", "--alert-critical", "alertModeCombo"):
        assert needle in cfg


def test_forecast_text_follows_the_clock_and_alert_row_wraps():
    model = (UI_DIR / "NotchModel.js").read_text(encoding="utf-8")
    fn = model[model.index("function forecast("):model.index("function windowView")]
    assert "nowMs" in fn and "fc.exhausts_at" in fn and "fc.seconds_until" not in fn  # exhausts_at - agora, nunca seconds_until
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    assert "Flow {" in cfg and "alertsDirty" in cfg


def test_compact_notch_uses_contract_level_not_fixed_thresholds():
    compact = (UI_DIR / "CompactRepresentation.qml").read_text(encoding="utf-8")
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    ring = (UI_DIR / "DualRing.qml").read_text(encoding="utf-8")
    presets = (UI_DIR / "Presets.js").read_text(encoding="utf-8")
    for src in (compact, main):
        assert "< 70" not in src and "<= 90" not in src and "maxUsagePercent" not in src
    model = (UI_DIR / "NotchModel.js").read_text(encoding="utf-8")
    assert "alert_level" in model and "elapsed_fraction" in model and "isActive" in model
    assert "NotchModel" in main
    assert "levelColor" in presets and 'return neutral' in presets  # sem nivel = neutro
    assert "Plasmoid.formFactor" in compact and "Accessible.description" in compact
    assert "free_trial_invites" in main and "inviteBadge" in compact and "healthDot" in compact
    assert "Canvas" in ring and "outerPct" in ring and "innerPct" in ring


def test_notch_config_entries_declared_and_exposed():
    xml = (PLASMOID_DIR / "contents" / "config" / "main.xml").read_text(encoding="utf-8")
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    for name in ("providerOrder", "hiddenProviders", "accentPreset"):
        assert f'name="{name}"' in xml and f"cfg_{name}" in cfg
    assert "highlightColor" in (UI_DIR / "main.qml").read_text(encoding="utf-8")

def test_config_general_exposes_notification_settings():
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    for needle in ("--set-notify-config", "--notify-warning", "--notify-critical", "--notify-early", "--notify-reset",
                   "--notify-mute", "notifyDirty", "setProviderMuted", "Accessible.name"):
        assert needle in cfg
    section = cfg[cfg.index("function saveNotifySettings"):cfg.index("// Executor de remoção de conta")]
    assert "shellQuote(configRoot.notifyMuted.join" in section  # nada vai ao shell sem aspas
    assert "notifyThresholdsEdited" in section and "hovered || activeFocus" in cfg and "Accessible.description" in cfg


def test_session_state_config_and_ui_wiring():
    xml = (PLASMOID_DIR / "contents" / "config" / "main.xml").read_text(encoding="utf-8")
    cfg = (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")
    for name in ("sessionState", "sessionAutoOpen", "sessionSound"):
        assert f'name="{name}"' in xml and f"cfg_{name}" in cfg
    assert xml.split('name="sessionState"')[1].split("</entry>")[0].count("<default>false</default>") == 1
    assert xml.split('name="sessionSound"')[1].split("</entry>")[0].count("<default>false</default>") == 1  # som desligado por padrao
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    assert "ai-usage-session-state" in (UI_DIR / "Collector.js").read_text(encoding="utf-8") and "interval: 5000" in main and "pillHovered" in main and "sessionSound === true" in main
    ring = (UI_DIR / "SessionMark.qml").read_text(encoding="utf-8")  # compartilhado por todos os estilos
    assert "reducedMotion" in ring and "!mark.reducedMotion" in ring and "Presets.warning" in ring


def test_session_attention_respects_pinned_hover_and_open_popup():
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    fn = main[main.index("function sessionAttention"):main.index("id: soundDataSource")]
    assert "!root.open && !root.pinned" in fn  # nao abre sobre popup ja aberto
    assert "root.pillHovered || root.popupHovered" in fn and "root.pinned" in fn  # nao fecha sob o mouse nem fixado
    assert "root.pinned = " not in fn  # nunca altera o estado fixado
    assert "ring.shown" in (UI_DIR / "DualRing.qml").read_text(encoding="utf-8")  # animacao para com o widget oculto


def test_session_polling_and_attention_respect_idle_hidden_and_defaults():
    main = (UI_DIR / "main.qml").read_text(encoding="utf-8")
    assert "root.visible && !root.idleHidden" in main  # nao polla com o widget oculto
    fn = main[main.index("function sessionAttention"):main.index("id: soundDataSource")]
    assert "!root.idleHidden" in fn and "sessionAutoOpen === true" in fn
    # instalacao antiga (sem o entrypoint leve): cai em `ai-usage-collector --session-state` antes do python3 -m
    cmd = (UI_DIR / "Collector.js").read_text(encoding="utf-8")
    assert "repositorios" not in cmd  # nenhum caminho pessoal no código
    assert "sessionFailed" in main
    xml = (PLASMOID_DIR / "contents" / "config" / "main.xml").read_text(encoding="utf-8")
    assert xml.split('name="sessionAutoOpen"')[1].split("</entry>")[0].count("<default>false</default>") == 1
    assert "property bool cfg_sessionAutoOpen: false" in (UI_DIR / "configGeneral.qml").read_text(encoding="utf-8")


def _package(tmp_path):
    """Roda package-release.sh; --no-isolation (offline) se setuptools e wheel estiverem instalados."""
    env = dict(os.environ)
    if importlib.util.find_spec("setuptools") and importlib.util.find_spec("wheel"):
        env["BUILD_ARGS"] = "--no-isolation"
    env["PYTHON"] = sys.executable
    result = subprocess.run([str(PACKAGE_SCRIPT), str(tmp_path)], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 0, f"package-release.sh failed: stdout={result.stdout}, stderr={result.stderr}"


def test_package_release_script_attributes_and_execution(tmp_path):
    """Verify package-release.sh exists, is executable, and produces plasmoid and wheel."""
    assert PACKAGE_SCRIPT.is_file(), "package-release.sh script must exist"
    assert os.access(PACKAGE_SCRIPT, os.X_OK), "package-release.sh must have executable bit set"

    _package(tmp_path)

    plasmoid_file = tmp_path / "org.kde.plasma.aiusage.plasmoid"
    assert plasmoid_file.is_file(), "Plasmoid package must be generated in target directory"

    wheels = list(tmp_path.glob("plasma_ai_usage_collector-*.whl"))
    assert len(wheels) == 1, f"Expected exactly one wheel in {tmp_path}, found: {wheels}"


def test_plasmoid_package_archive_contents(tmp_path):
    """Verify generated .plasmoid package is a valid zip with metadata at root and required QML files."""
    _package(tmp_path)

    plasmoid_file = tmp_path / "org.kde.plasma.aiusage.plasmoid"
    assert plasmoid_file.is_file()

    with zipfile.ZipFile(plasmoid_file, "r") as zf:
        namelist = zf.namelist()

        # Root metadata.json
        assert "metadata.json" in namelist, "metadata.json must be located at the root of the .plasmoid archive"

        # Required components
        expected_files = [
            "contents/ui/main.qml",
            "contents/ui/CompactRepresentation.qml",
            "contents/ui/FullRepresentation.qml",
            "contents/ui/AccountCard.qml",
            "contents/ui/configGeneral.qml",
            "contents/ui/ProviderLogo.qml",
            "contents/ui/LOGOS.md",
            *(f"contents/ui/logo-{p}.svg" for p in LOGO_PROVIDERS),
            "contents/config/main.xml",
            "contents/config/config.qml",
        ]
        for f in expected_files:
            assert f in namelist, f"Missing file in plasmoid package: {f}"

        # Cleanliness: no temp/swap/cache files
        for name in namelist:
            assert not name.endswith("~"), f"Temporary file found in plasmoid: {name}"
            assert not name.endswith(".swp"), f"Vim swap file found in plasmoid: {name}"
            assert not name.endswith(".bak"), f"Backup file found in plasmoid: {name}"
            assert "__pycache__" not in name, f"Python cache found in plasmoid: {name}"
            assert ".git" not in name, f"Git file found in plasmoid: {name}"
            assert ".DS_Store" not in name, f"macOS artifact found in plasmoid: {name}"

        # Traduções: os .mo não são versionados, então só chegam ao pacote se o script os compilar
        for lang in ("en", "pt_BR"):
            assert f"contents/locale/{lang}/LC_MESSAGES/plasma_applet_org.kde.plasma.aiusage.mo" in namelist
        assert not any(n.startswith(".venv") or ".venv/" in n for n in namelist)

        # Verify metadata validity inside package
        meta_data = json.loads(zf.read("metadata.json").decode("utf-8"))
        assert meta_data.get("KPlugin", {}).get("Id") == "org.kde.plasma.aiusage"
        assert meta_data.get("KPackageStructure") == "Plasma/Applet"


def test_collector_wheel_contents_and_entrypoint(tmp_path):
    """Verify generated wheel contains collector packages and ai-usage-collector entrypoint."""
    _package(tmp_path)

    wheels = list(tmp_path.glob("plasma_ai_usage_collector-*.whl"))
    assert len(wheels) == 1, f"Expected exactly one wheel in {tmp_path}, found: {wheels}"
    wheel_file = wheels[0]

    with zipfile.ZipFile(wheel_file, "r") as zf:
        namelist = zf.namelist()

        # Verify collector modules are present
        expected_modules = [
            "ai_usage_collector/__init__.py",
            "ai_usage_collector/cli.py",
            "ai_usage_collector/contract.py",
            "ai_usage_collector/collector.py",
            "ai_usage_collector/discovery.py",
            "ai_usage_collector/config.py",
            "ai_usage_collector/capture.py",
            "ai_usage_collector/extractors/claude.py",
            "ai_usage_collector/extractors/codex.py",
            "ai_usage_collector/extractors/gemini.py",
        ]
        for mod in expected_modules:
            assert mod in namelist, f"Missing Python module in wheel: {mod}"

        # Verify entry point
        ep_files = [n for n in namelist if n.endswith("entry_points.txt")]
        assert ep_files, "entry_points.txt must be present in wheel dist-info"
        ep_content = zf.read(ep_files[0]).decode("utf-8")
        assert "ai-usage-collector = ai_usage_collector.cli:main" in ep_content
        assert "ai-usage-session-state = ai_usage_collector.session_state:states_main" in ep_content


def test_github_actions_release_workflow_configuration():
    """Verify release.yml workflow has required triggers, permissions, and build/release steps."""
    assert RELEASE_WORKFLOW.is_file(), ".github/workflows/release.yml must exist"

    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    # Triggers
    assert "branches:" in content and "main" in content
    assert "tags:" in content and "'v*'" in content
    assert "workflow_dispatch:" in content

    # Permissions
    assert "contents: write" in content  # só no job (ver teste de segurança)

    # Steps
    assert "actions/checkout@" in content
    assert "fetch-depth: 0" in content
    assert "actions/setup-python@" in content
    assert "3.12" in content
    assert "pip install build" in content
    assert "scripts/package-release.sh" in content
    assert "softprops/action-gh-release@" in content

    # Artifacts attached
    assert "dist/*.plasmoid" in content
    assert "dist/*.whl" in content

    # Release naming & tag logic
    assert "latest" in content


def test_package_release_fails_without_catalog(tmp_path):
    """Sem o .po de um idioma o script falha em vez de publicar pacote sem traduções."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT, repo, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "__pycache__", "*.egg-info", ".scratch"))
    (repo / "po" / "pt_BR.po").unlink()
    result = subprocess.run([str(repo / "scripts" / "package-release.sh"), str(tmp_path / "out")], capture_output=True, text=True, check=False)
    assert result.returncode != 0


def test_versions_stay_in_sync():
    import ai_usage_collector

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert ai_usage_collector.__version__ == version == meta["KPlugin"]["Version"]


def test_release_workflow_security_hardening():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    # nenhuma expressão github.* dentro de run: (injeção); passa por env:
    for block in re.findall(r"^\s+run:\s*[|>]?-?\s*\n((?:\s{10,}.*\n?)+)|^\s+run:\s*(.+)$", content, re.M):
        assert "${{" not in "".join(block)
    assert "pull_request_target" not in content
    # actions fixadas em SHA completo de commit
    uses = re.findall(r"^\s+uses:\s*(\S+)", content, re.M)
    assert len(uses) == 8
    for ref in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
    # permissão de escrita só no job; workflow sem permissões
    assert re.search(r"^permissions:\s*\{\}\s*$", content, re.M)
    assert not re.search(r"^permissions:\s*\n\s+contents: write", content, re.M)
    job = content[content.index("jobs:"):]
    assert re.search(r"^    permissions:\n      contents: write", job, re.M)
    assert "TAG_REF: ${{ github.ref_name }}" in content and '"$TAG_REF"' in content
    assert "[0-9]+\\.[0-9]+\\.[0-9]+" in content
    # PyPI: OIDC só no job de publicação, tag válida, sem segredo do PyPI
    build, publish = _job("pypi-build"), _job("pypi-publish")
    for j in (build, publish):
        assert re.search(r"^    if: github\.ref_type == 'tag' && startsWith\(github\.ref_name, 'v'\)$", j, re.M)
    assert re.search(r"^    needs: pypi-build$", publish, re.M)
    assert re.search(r"^    environment: pypi$", publish, re.M)
    assert re.search(r"^    permissions:\n      id-token: write\n      contents: read\n", publish, re.M)
    assert re.search(r"^    permissions:\n      contents: read\n", build, re.M)
    assert content.count("id-token") == 1
    assert "skip-existing" not in content and "repository-url" not in content
    assert not re.search(r"pypi[_-]?(api[_-]?)?token|PYPI_|password:", content, re.I)
    assert content.count("secrets.") == 1
    assert "check-release-versions.py" in build and "twine check" in build
    assert "dist/*.whl" in _job("release")


def _job(name: str) -> str:
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", content, re.M | re.S)
    assert m, f"job {name} ausente"
    return m.group(1)


@pytest.mark.parametrize(
    "tag,pkg,meta,ok",
    [
        ("v1.2.3", "1.2.3", "1.2.3", True),
        ("1.2.3", "1.2.3", "1.2.3", True),
        ("v1.2.3-rc1", "1.2.3-rc1", "1.2.3-rc1", True),
        ("v1.2.4", "1.2.3", "1.2.3", False),
        ("v1.2.3", "1.2.4", "1.2.3", False),
        ("v1.2.3", "1.2.3", "1.2.4", False),
        ("v1.2.3-rc1", "1.2.3", "1.2.3", False),
        ("vv1.2.3", "1.2.3", "1.2.3", False),
    ],
)
@pytest.mark.skipif(sys.version_info < (3, 11), reason="script usa tomllib (CI roda 3.12)")
def test_check_release_versions(tmp_path, tag, pkg, meta, ok):
    (tmp_path / "plasmoid").mkdir()
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{pkg}"\n', encoding="utf-8")
    (tmp_path / "plasmoid" / "metadata.json").write_text(json.dumps({"KPlugin": {"Version": meta}}), encoding="utf-8")
    script = REPO_ROOT / "scripts" / "check-release-versions.py"
    result = subprocess.run([sys.executable, str(script), tag, str(tmp_path)], capture_output=True, text=True)
    assert (result.returncode == 0) is ok


@pytest.mark.skipif(sys.version_info < (3, 11), reason="script usa tomllib (CI roda 3.12)")
def test_check_release_versions_passes_on_real_repo():
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))["KPlugin"]["Version"]
    script = REPO_ROOT / "scripts" / "check-release-versions.py"
    assert subprocess.run([sys.executable, str(script), f"v{meta}"]).returncode == 0
