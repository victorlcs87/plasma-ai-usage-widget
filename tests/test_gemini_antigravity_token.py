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
        "expiry": "2030-01-01T00:00:00Z",
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
