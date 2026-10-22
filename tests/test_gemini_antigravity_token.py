"""Fonte de credencial Gemini: arquivo da CLI Antigravity (somente leitura)."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_usage_collector.capture import get_active_credentials, get_active_gemini_credentials
from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config
from ai_usage_collector.identity import creds_identity
from test_cli_capture_current import make_jwt

AGY_PAYLOAD = {
    "token": {
        "access_token": "ya29.agy_access",
        "token_type": "Bearer",
        "refresh_token": "1//agy_refresh",
        "expiry": "2099-01-01T00:00:00Z",
        "expires_in": 3599,
    },
    "auth_method": "oauth",
    "id_token": make_jwt({"email": "agy.user@example.com", "sub": "123"}),
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_CONFIG_DIR", raising=False)
    h = tmp_path / "_home"  # HOME ja isolado pelo conftest
    (h / ".gemini" / "antigravity-cli").mkdir(parents=True)
    return h


@pytest.fixture(autouse=True)
def _no_real_keyring():
    """Nenhum teste consulta o chaveiro real da maquina (secret-tool)."""
    with patch("subprocess.run", side_effect=_keyring()):
        yield


def _agy_file(base: Path, payload=AGY_PAYLOAD) -> Path:
    f = base / "antigravity-cli" / "antigravity-oauth-token"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(payload))
    f.chmod(0o640)
    return f


def _keyring(stdout="", rc=1):
    def run(cmd, *a, **k):
        r = MagicMock()
        r.returncode, r.stdout = rc, stdout
        return r
    return run


def test_reads_nested_token_normalized(home):
    f = _agy_file(home / ".gemini")
    with patch("subprocess.run", side_effect=_keyring()):
        creds, src = get_active_gemini_credentials()
    assert src == str(f)
    assert creds["access_token"] == "ya29.agy_access"
    assert creds["refresh_token"] == "1//agy_refresh"
    assert creds["id_token"] == AGY_PAYLOAD["id_token"]
    assert "token" not in creds
    assert get_active_credentials("gemini")["access_token"] == "ya29.agy_access"


def test_identity_from_id_token(home):
    _agy_file(home / ".gemini")
    with patch("subprocess.run", side_effect=_keyring()):
        creds, _ = get_active_gemini_credentials()
    assert creds_identity("gemini", creds).email == "agy.user@example.com"


def test_priority_keyring_then_oauth_creds_then_agy(home):
    _agy_file(home / ".gemini")
    with patch("subprocess.run", side_effect=_keyring()):
        assert get_active_gemini_credentials()[0]["access_token"] == "ya29.agy_access"
        (home / ".gemini" / "oauth_creds.json").write_text(json.dumps({"access_token": "file_tok"}))
        assert get_active_gemini_credentials()[0]["access_token"] == "file_tok"
    with patch("subprocess.run", side_effect=_keyring(json.dumps({"access_token": "ring_tok"}), 0)):
        creds, src = get_active_gemini_credentials()
    assert creds["access_token"] == "ring_tok" and src == "keyring (secret-tool)"


def test_respects_gemini_config_dir(home, tmp_path, monkeypatch):
    other = tmp_path / "other_gemini"
    f = _agy_file(other)
    monkeypatch.setenv("GEMINI_CONFIG_DIR", str(other))
    creds, src = get_active_gemini_credentials()
    assert src == str(f) and creds["access_token"] == "ya29.agy_access"


def test_capture_isolated_copy_and_original_untouched(home, tmp_path, capsys):
    f = _agy_file(home / ".gemini")
    before = (f.read_bytes(), f.stat().st_mtime_ns, stat.S_IMODE(f.stat().st_mode))
    cfg_path, cache = tmp_path / "config.json", tmp_path / "status.json"
    calls = []

    def run(cmd, *a, **k):
        calls.append(cmd)
        return _keyring()(cmd)

    with patch("subprocess.run", side_effect=run):
        code = main(["--capture-current", "gemini", "--config-path", str(cfg_path), "--cache-path", str(cache)])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "agy.user@example.com" in out.out
    assert "ya29.agy_access" not in out.out + out.err and "1//agy_refresh" not in out.out + out.err

    acc = next(a for a in load_config(cfg_path)["agents"]["gemini"]["accounts"] if a["source"] == "captured")
    copy = Path(acc["credential_path"])
    assert copy != f and f.parent not in copy.parents
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert json.loads(copy.read_text())["access_token"] == "ya29.agy_access"

    assert (f.read_bytes(), f.stat().st_mtime_ns, stat.S_IMODE(f.stat().st_mode)) == before
    assert not any("store" in c for c in calls)  # nunca grava no chaveiro


def test_no_source_still_reports_missing(home, tmp_path, capsys):
    (home / ".gemini" / "antigravity-cli").rmdir()
    with patch("subprocess.run", side_effect=_keyring()):
        code = main(["--capture-current", "gemini", "--config-path", str(tmp_path / "c.json"),
                     "--cache-path", str(tmp_path / "s.json")])
    assert code == 1
    assert "antigravity-oauth-token" in capsys.readouterr().err


# --- ticket 43: a conta capturada acompanha o arquivo vivo da Antigravity ---

def _captured(tmp_path, payload=AGY_PAYLOAD):
    """Copia isolada como a captura a grava: plana, com `expiry` ISO."""
    p = tmp_path / "profiles" / "gemini-x" / "oauth_creds.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_read_gemini_file_from(payload)))
    return p


def _read_gemini_file_from(payload):
    return {**{k: v for k, v in payload.items() if k != "token"}, **payload["token"]}


def test_expiry_iso_is_understood(tmp_path):
    from ai_usage_collector.discovery import discover_gemini
    past = {**AGY_PAYLOAD, "token": {**AGY_PAYLOAD["token"], "expiry": "2020-01-01T00:00:00Z", "refresh_token": ""}}
    p = _captured(tmp_path, past)
    assert discover_gemini(p)["status"] != "valid"
    ok = _captured(tmp_path / "b")
    assert discover_gemini(ok)["status"] == "valid"


def test_sync_pulls_fresh_token_without_touching_live(home, tmp_path):
    from ai_usage_collector.capture import sync_gemini_from_antigravity
    stale = {**AGY_PAYLOAD, "token": {**AGY_PAYLOAD["token"], "access_token": "ya29.old", "expiry": "2020-01-01T00:00:00Z"}}
    copy = _captured(tmp_path, stale)
    live = _agy_file(home / ".gemini")  # token novo, expiry futuro
    before = (live.read_bytes(), live.stat().st_mtime_ns)
    assert sync_gemini_from_antigravity(copy) is True
    assert json.loads(copy.read_text())["access_token"] == "ya29.agy_access"
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert (live.read_bytes(), live.stat().st_mtime_ns) == before


def test_sync_ignores_other_identity_and_older_live(home, tmp_path):
    from ai_usage_collector.capture import sync_gemini_from_antigravity
    copy = _captured(tmp_path)
    original = copy.read_text()
    other = {**AGY_PAYLOAD, "id_token": make_jwt({"email": "outra@example.com", "sub": "9"})}
    _agy_file(home / ".gemini", other)
    assert sync_gemini_from_antigravity(copy) is False
    older = {**AGY_PAYLOAD, "token": {**AGY_PAYLOAD["token"], "expiry": "2025-01-01T00:00:00Z"}}
    _agy_file(home / ".gemini", older)
    assert sync_gemini_from_antigravity(copy) is False
    assert copy.read_text() == original


@pytest.mark.parametrize("live", [None, "{not json", "[1, 2]"])
def test_sync_leaves_copy_intact_on_bad_live(home, tmp_path, live):
    from ai_usage_collector.capture import sync_gemini_from_antigravity
    copy = _captured(tmp_path)
    original = copy.read_text()
    if live is not None:
        f = _agy_file(home / ".gemini")
        f.write_text(live)
    assert sync_gemini_from_antigravity(copy) is False
    assert copy.read_text() == original


def test_expiry_with_zone_and_nanoseconds(tmp_path):
    from ai_usage_collector.discovery import discover_gemini
    ns = {**AGY_PAYLOAD, "token": {**AGY_PAYLOAD["token"], "expiry": "2026-10-21T14:17:03.756448137-03:00", "refresh_token": ""}}
    assert discover_gemini(_captured(tmp_path, ns))["status"] != "valid"  # passado
    far = {**AGY_PAYLOAD, "token": {**AGY_PAYLOAD["token"], "expiry": "2099-10-21T14:17:03.756448137-03:00"}}
    assert discover_gemini(_captured(tmp_path / "b", far))["status"] == "valid"


def _collect(home, tmp_path, sync=None):
    """Coleta completa com a conta capturada de copia vencida e arquivo vivo com expiry futuro."""
    from ai_usage_collector.collector import collect_and_save
    from ai_usage_collector.config import save_config
    stale = {**AGY_PAYLOAD, "token": {**AGY_PAYLOAD["token"], "access_token": "ya29.old", "expiry": "2020-01-01T00:00:00Z", "refresh_token": ""}}
    copy = _captured(tmp_path, stale)
    _agy_file(home / ".gemini")
    cfg = tmp_path / "config.json"
    save_config({"agents": {"gemini": {"accounts": [
        {"id": "g1", "label": "G", "source": "captured", "credential_path": str(copy), "gemini_dir": str(copy.parent)}
    ]}}}, cfg)
    patches = [patch("subprocess.run", side_effect=_keyring()),
               patch("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", return_value=None)]
    if sync:
        patches.append(patch("ai_usage_collector.collector.sync_gemini_from_antigravity", side_effect=sync))
    for p in patches:
        p.start()
    try:
        return collect_and_save(config_path=cfg, cache_path=tmp_path / "status.json")
    finally:
        patch.stopall()


def test_collect_marks_captured_account_valid(home, tmp_path):
    acc = _collect(home, tmp_path)["agents"]["gemini"]["accounts"][0]
    assert acc["health"]["status"] == "valid"


def test_collect_survives_sync_oserror(home, tmp_path, capsys):
    status = _collect(home, tmp_path, sync=OSError("disco cheio"))
    assert len(status["agents"]["gemini"]["accounts"]) == 1
    assert "nao sincronizado" in capsys.readouterr().err


def test_sync_replaces_stale_expiry_date_in_copy(home, tmp_path):
    from ai_usage_collector.capture import sync_gemini_from_antigravity
    from ai_usage_collector.discovery import discover_gemini
    _agy_file(home / ".gemini")
    old = {**_read_gemini_file_from(AGY_PAYLOAD), "expiry_date": 1_600_000_000_000, "expiry": "2020-01-01T00:00:00Z"}
    copy = tmp_path / "profiles" / "gemini-x" / "oauth_creds.json"
    copy.parent.mkdir(parents=True)
    copy.write_text(json.dumps(old))
    assert sync_gemini_from_antigravity(copy)
    assert discover_gemini(copy)["status"] == "valid"
