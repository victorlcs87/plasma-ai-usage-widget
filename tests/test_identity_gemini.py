"""Identidade da Conta no Gemini (ADR-0008): email Google, arquivo e chaveiro simulado.

O HOME e falso (conftest); o chaveiro (`secret-tool`) e simulado no limite do processo.
"""

import base64
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config, save_config, save_secure_json

PAST_MS = 1_000_000_000_000  # 2001
FUTURE_MS = 4_000_000_000_000  # 2096


def _jwt(email: str) -> str:
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64({'email': email, 'sub': 'sub-' + email})}.sig"


def _creds(email: str, access: str, refresh: str, expiry_ms: int = FUTURE_MS) -> dict:
    return {"access_token": access, "refresh_token": refresh, "id_token": _jwt(email),
            "token_type": "Bearer", "expiry_date": expiry_ms}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Keyring:
    def __init__(self):
        self.payload: str | None = None
        self.fail_store = False


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = Path(os.environ["HOME"])
    monkeypatch.delenv("GEMINI_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_CONFIG_DIR", raising=False)
    monkeypatch.setattr("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api", lambda *a, **k: None)

    keyring = Keyring()
    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):
        if cmd[0] != "secret-tool":
            return real_run(cmd, *a, **kw)
        if cmd[1] == "lookup":
            ok = keyring.payload is not None
            return subprocess.CompletedProcess(cmd, 0 if ok else 1, keyring.payload or "", "")
        if keyring.fail_store:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        keyring.payload = kw["input"]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    class Env:
        root = tmp_path
        config = tmp_path / "cfg" / "config.json"
        cache = tmp_path / "status.json"
        sys_creds = home / ".gemini" / "oauth_creds.json"
        kr = keyring

        def profile(self, name: str, creds: dict) -> Path:
            d = tmp_path / "cfg" / "profiles" / name
            save_secure_json(creds, d / "oauth_creds.json")
            return d

        def system(self, creds: dict | None = None, keyring_creds: dict | None = None):
            if creds:
                save_secure_json(creds, self.sys_creds)
            if keyring_creds:
                keyring.payload = json.dumps(keyring_creds)

        def save_cfg(self, accounts: list[dict]):
            save_config({"version": 1, "agents": {"gemini": {"accounts": accounts},
                                                  "claude": {"accounts": []}, "codex": {"accounts": []}}},
                        self.config)

        def run(self, *args: str) -> int:
            return main([*args, "--config-path", str(self.config), "--cache-path", str(self.cache)])

        def status(self) -> list[dict]:
            self.run("--status")
            return _read(self.cache)["agents"]["gemini"]["accounts"]

        def active_ids(self) -> list[str]:
            return [a["id"] for a in self.status() if a["isActive"]]

    return Env()


def _acc(acc_id: str, profile: Path, label: str | None = None) -> dict:
    return {"id": acc_id, "label": label or acc_id, "source": "captured",
            "credential_path": str(profile / "oauth_creds.json"), "gemini_dir": str(profile)}


def _legacy_default(env) -> dict:
    return {"id": "default", "label": "Gemini (Padrão)", "source": "auto", "credential_path": str(env.sys_creds)}


def test_default_config_does_not_point_gemini_to_system_path(env):
    assert load_config(env.config)["agents"]["gemini"]["accounts"] == []


def test_active_detected_by_email_after_token_rotation(env):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("A@x.com", "tok-a-rotated", "ref-a-rotated"))
    assert env.active_ids() == ["a"]


def test_keyring_valid_prevails_over_stale_file(env):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    # Arquivo (conta A) com expiracao antiga; chaveiro (conta B) valido, em formato aninhado.
    env.system(_creds("a@x.com", "tok-a-old", "ref-a-old", PAST_MS), keyring_creds={
        "token": {"access_token": "tok-b-kr", "refresh_token": "ref-b-kr", "expiry": "2096-01-01T00:00:00Z"},
        "id_token": _jwt("b@x.com")})
    assert env.active_ids() == ["b"]


def test_legacy_default_with_stale_file_and_valid_keyring_is_valid_not_expired(env):
    env.system(_creds("a@x.com", "tok-old", "", PAST_MS) | {"refresh_token": None},
               keyring_creds=_creds("a@x.com", "tok-kr", "ref-kr"))
    env.save_cfg([_legacy_default(env)])

    [acc] = env.status()
    assert acc["isActive"] and acc["health"]["status"] == "valid"
    migrated = Path(load_config(env.config)["agents"]["gemini"]["accounts"][0]["credential_path"])
    assert migrated.resolve() != env.sys_creds.resolve()
    assert _read(migrated)["access_token"] == "tok-kr"  # a credencial do chaveiro foi a salva
    assert stat.S_IMODE(os.stat(migrated).st_mode) == 0o600
    assert load_config(env.config)["agents"]["gemini"]["accounts"][0]["credential_path"] == str(migrated)  # idempotente


def test_legacy_default_only_in_keyring_is_migrated_not_dropped(env):
    env.system(keyring_creds=_creds("k@x.com", "tok-kr", "ref-kr"))
    env.save_cfg([_legacy_default(env)])
    [acc] = load_config(env.config)["agents"]["gemini"]["accounts"]
    assert _read(Path(acc["credential_path"]))["access_token"] == "tok-kr"
    assert "k@x.com" in acc["label"]


def test_duplicates_are_merged_preserving_renamed_label(env):
    p1 = env.profile("one", _creds("a@x.com", "tok-1", "ref-1"))
    p2 = env.profile("two", _creds("a@x.com", "tok-2", "ref-1"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("one", p1, label="Gemini (a@x.com)"), _acc("b", pb, label="Gemini (b@x.com)"),
                  _acc("two", p2, label="Pessoal")])
    accs = load_config(env.config)["agents"]["gemini"]["accounts"]
    assert sorted(a["label"] for a in accs) == ["Gemini (b@x.com)", "Pessoal"]
    assert (p1 / "oauth_creds.json").exists() and (p2 / "oauth_creds.json").exists()


def test_switch_a_b_a_applies_file_and_keyring_and_preserves_renewed_tokens(env):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("a@x.com", "tok-a", "ref-a"), keyring_creds=_creds("a@x.com", "tok-a", "ref-a"))

    assert env.run("--switch-account", "gemini", "b") == 0
    assert env.active_ids() == ["b"]
    assert _read(env.sys_creds)["access_token"] == "tok-b"
    assert json.loads(env.kr.payload)["access_token"] == "tok-b"
    assert stat.S_IMODE(os.stat(env.sys_creds).st_mode) == 0o600

    # O Gemini CLI renova B no chaveiro (o arquivo continua velho).
    env.kr.payload = json.dumps(_creds("b@x.com", "tok-b-renewed", "ref-b-renewed"))
    assert env.run("--switch-account", "gemini", "a") == 0
    assert _read(pb / "oauth_creds.json")["refresh_token"] == "ref-b-renewed"
    assert env.active_ids() == ["a"]

    assert env.run("--switch-account", "gemini", "b") == 0
    assert json.loads(env.kr.payload)["refresh_token"] == "ref-b-renewed"
    assert _read(env.sys_creds)["refresh_token"] == "ref-b-renewed"
    assert env.active_ids() == ["b"]


def test_unknown_system_credential_is_captured_before_overwrite(env):
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("b", pb)])
    env.system(keyring_creds=_creds("x@x.com", "tok-x", "ref-x"))

    assert env.run("--switch-account", "gemini", "b") == 0
    accs = load_config(env.config)["agents"]["gemini"]["accounts"]
    new = next(a for a in accs if a["id"] != "b")
    assert _read(Path(new["credential_path"]))["access_token"] == "tok-x"
    assert "x@x.com" in new["label"]
    assert env.active_ids() == ["b"]


def test_failed_keyring_store_rolls_back_file(env, capsys):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("a@x.com", "tok-a", "ref-a"), keyring_creds=_creds("a@x.com", "tok-a", "ref-a"))
    before = (env.sys_creds.read_bytes(), env.kr.payload)
    env.kr.fail_store = True
    capsys.readouterr()

    assert env.run("--switch-account", "gemini", "b") == 1
    assert "chaveiro" in capsys.readouterr().err
    assert (env.sys_creds.read_bytes(), env.kr.payload) == before


def test_profile_with_newer_expiry_is_not_regressed_by_system(env):
    pa = env.profile("a", _creds("a@x.com", "tok-a-new", "ref-a-new", FUTURE_MS))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("a@x.com", "tok-a-old", "ref-a-old", PAST_MS + 1))

    assert env.run("--switch-account", "gemini", "b") == 0
    assert _read(pa / "oauth_creds.json")["refresh_token"] == "ref-a-new"
    assert len(list(pa.glob("oauth_creds.json.bak-*"))) == 1


def test_collector_never_writes_renewed_token_to_disk(env, monkeypatch):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a", PAST_MS))
    env.save_cfg([_acc("a", pa)])
    before = (pa / "oauth_creds.json").read_bytes()
    env.system(keyring_creds=_creds("a@x.com", "tok-kr", "ref-kr"))
    monkeypatch.setattr("ai_usage_collector.extractors.gemini.fetch_gemini_quota_api",
                        lambda token, *a, **k: {"buckets": []})
    env.run("--status")
    assert (pa / "oauth_creds.json").read_bytes() == before
    assert not env.sys_creds.exists()


def test_rotated_keyring_without_id_token_does_not_take_identity_of_stale_file(env):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("b@x.com", "tok-b-stale", "ref-b-stale", PAST_MS),
               keyring_creds={"access_token": "tok-a-rot", "refresh_token": "ref-a-rot", "expiry_date": FUTURE_MS})
    before = (pb / "oauth_creds.json").read_bytes()

    env.run("--switch-account", "gemini", "b")
    assert (pb / "oauth_creds.json").read_bytes() == before


def test_keyring_store_preserves_nested_format(env):
    pa = env.profile("a", _creds("a@x.com", "tok-a", "ref-a"))
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(keyring_creds={"serverName": "antigravity", "token": _creds("a@x.com", "tok-a", "ref-a")})

    assert env.run("--switch-account", "gemini", "b") == 0
    stored = json.loads(env.kr.payload)
    assert stored["serverName"] == "antigravity"
    assert stored["token"]["access_token"] == "tok-b"
    assert "access_token" not in stored


def test_keyring_untouched_when_path_override_is_active(env, monkeypatch, tmp_path):
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("b", pb)])
    monkeypatch.setenv("GEMINI_CONFIG_DIR", str(tmp_path / "custom"))

    assert env.run("--switch-account", "gemini", "b") == 0
    assert env.kr.payload is None
    assert _read(tmp_path / "custom" / "oauth_creds.json")["access_token"] == "tok-b"


def test_failed_keyring_store_error_is_actionable_and_leaks_nothing(env, capsys):
    pb = env.profile("b", _creds("b@x.com", "tok-b", "ref-b"))
    env.save_cfg([_acc("b", pb)])
    env.kr.fail_store = True
    capsys.readouterr()

    assert env.run("--switch-account", "gemini", "b") == 1
    err = capsys.readouterr().err
    assert "Secret Service" in err and "tok-b" not in err
