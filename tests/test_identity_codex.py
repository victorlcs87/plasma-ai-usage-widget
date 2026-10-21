"""Identidade da Conta no Codex (ADR-0008): deteccao, migracao, fusao e troca pela CLI.

A identidade e o `account_id` do auth.json (ou do claim do id_token JWT); nao ha arquivo de
estado separado. O sistema e redirecionado via CODEX_HOME para um diretorio temporario.
"""

import base64
import json
import os
import stat
from pathlib import Path

import pytest

from ai_usage_collector import capture
from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config, save_config, save_secure_json
from ai_usage_collector.identity import credential_identity


def _jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def _creds(access: str, refresh: str, account_id: str | None, email: str | None = None) -> dict:
    tokens = {"access_token": access, "refresh_token": refresh,
              "id_token": _jwt({"email": email} if email else {"sub": "u"})}
    if account_id:
        tokens["account_id"] = account_id
    return {"auth_mode": "chatgpt", "tokens": tokens}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tok(path: Path, key: str = "access_token") -> str:
    return _read(path)["tokens"][key]


@pytest.fixture
def env(tmp_path, monkeypatch):
    sys_dir = tmp_path / "sys_codex"
    monkeypatch.setenv("CODEX_HOME", str(sys_dir))
    monkeypatch.delenv("CODEX_AUTH_PATH", raising=False)

    class Env:
        config = tmp_path / "cfg" / "config.json"
        cache = tmp_path / "status.json"
        sys_creds = sys_dir / "auth.json"

        def profile(self, name: str, creds: dict) -> Path:
            d = tmp_path / "cfg" / "profiles" / name
            save_secure_json(creds, d / "auth.json")
            return d

        def system(self, creds: dict):
            save_secure_json(creds, self.sys_creds)

        def save_cfg(self, accounts: list[dict]):
            save_config({"version": 1, "agents": {"claude": {"accounts": []},
                                                  "codex": {"accounts": accounts},
                                                  "gemini": {"accounts": []}}}, self.config)

        def run(self, *args: str) -> int:
            return main([*args, "--config-path", str(self.config), "--cache-path", str(self.cache)])

        def active_ids(self) -> list[str]:
            self.run("--status")
            accs = _read(self.cache)["agents"]["codex"]["accounts"]
            return [a["id"] for a in accs if a["isActive"]]

    return Env()


def _acc(acc_id: str, profile: Path, label: str | None = None, **extra) -> dict:
    return {"id": acc_id, "label": label or acc_id, "source": "captured",
            "credential_path": str(profile / "auth.json"), "codex_dir": str(profile), **extra}


def _legacy(env) -> dict:
    return {"id": "default", "label": "Codex (Padrão)", "source": "auto", "credential_path": str(env.sys_creds)}


def test_default_config_does_not_point_codex_to_system_path(env):
    assert load_config(env.config.parent / "fresh.json")["agents"]["codex"]["accounts"] == []


def test_identity_from_account_id_and_jwt_claim(tmp_path):
    f = tmp_path / "auth.json"
    save_secure_json(_creds("t", "r", "Acc-1", "a@x.com"), f)
    assert tuple(credential_identity("codex", f)) == ("acc-1", "a@x.com")
    # Sem tokens.account_id: usa o claim chatgpt_account_id do id_token.
    claim = {"https://api.openai.com/auth": {"chatgpt_account_id": "acc-2"}, "email": "b@x.com"}
    save_secure_json({"tokens": {"access_token": "t", "id_token": _jwt(claim)}}, f)
    assert tuple(credential_identity("codex", f)) == ("acc-2", "b@x.com")
    save_secure_json({"tokens": {"access_token": "t"}}, f)
    assert credential_identity("codex", f) is None


def test_active_detected_by_identity_after_token_rotation(env):
    pa = env.profile("a", _creds("tok-a", "ref-a", "acc-a"))
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb, active=True)])
    env.system(_creds("tok-a-rotated", "ref-a-rotated", "acc-a"))

    assert env.active_ids() == ["a"]
    assert all("active" not in a for a in load_config(env.config)["agents"]["codex"]["accounts"])


def test_unknown_system_identity_marks_none_active(env):
    pa = env.profile("a", _creds("tok-a", "ref-a", "acc-a"))
    env.save_cfg([_acc("a", pa)])
    env.system(_creds("tok-x", "ref-x", "acc-x"))
    assert env.active_ids() == []


def test_legacy_default_is_migrated_to_isolated_profile_idempotently(env):
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.system(_creds("tok-a", "ref-a", "acc-a", "a@x.com"))
    env.save_cfg([_legacy(env), _acc("b", pb)])

    cfg1 = load_config(env.config)
    accs = cfg1["agents"]["codex"]["accounts"]
    assert [a["id"] for a in accs] == ["default", "b"]
    migrated = Path(accs[0]["credential_path"])
    assert migrated.resolve() != env.sys_creds.resolve()
    assert _tok(migrated) == "tok-a"
    assert stat.S_IMODE(os.stat(migrated).st_mode) == 0o600
    assert "a@x.com" in accs[0]["label"]

    assert load_config(env.config) == cfg1  # idempotente
    assert env.active_ids() == ["default"]
    assert _tok(env.sys_creds) == "tok-a"  # sistema intacto


def test_legacy_default_without_system_credential_is_dropped(env):
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_legacy(env), _acc("b", pb)])
    assert [a["id"] for a in load_config(env.config)["agents"]["codex"]["accounts"]] == ["b"]


def test_legacy_default_merges_into_account_with_same_identity(env):
    pa = env.profile("a", _creds("tok-a-old", "ref-a-old", "acc-a"))
    env.system(_creds("tok-a-new", "ref-a-new", "acc-a"))
    env.save_cfg([_legacy(env), _acc("a", pa, label="Trabalho")])

    accs = load_config(env.config)["agents"]["codex"]["accounts"]
    assert [(a["id"], a["label"]) for a in accs] == [("a", "Trabalho")]
    assert _tok(pa / "auth.json") == "tok-a-new"


def test_duplicates_are_merged_preserving_renamed_label(env):
    p1 = env.profile("one", _creds("tok-1", "ref-1", "acc-a", "a@x.com"))
    p2 = env.profile("two", _creds("tok-2", "ref-1", "acc-a", "a@x.com"))
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_acc("one", p1, label="Codex (a@x.com)"), _acc("b", pb, label="Codex"),
                  _acc("two", p2, label="Pessoal")])

    accs = load_config(env.config)["agents"]["codex"]["accounts"]
    assert sorted(a["label"] for a in accs) == ["Codex", "Pessoal"]
    assert load_config(env.config)["agents"]["codex"]["accounts"] == accs
    assert (p1 / "auth.json").exists() and (p2 / "auth.json").exists()


def test_duplicates_with_divergent_tokens_are_kept(env):
    p1 = env.profile("one", _creds("tok-1", "ref-1", "acc-a"))
    p2 = env.profile("two", _creds("tok-2", "ref-2", "acc-a"))
    env.save_cfg([_acc("one", p1), _acc("two", p2)])
    assert len(load_config(env.config)["agents"]["codex"]["accounts"]) == 2


def test_switch_a_b_a_preserves_renewed_tokens(env):
    pa = env.profile("a", _creds("tok-a", "ref-a", "acc-a"))
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a", "acc-a"))

    assert env.run("--switch-account", "codex", "b") == 0
    assert env.active_ids() == ["b"]
    assert _tok(env.sys_creds) == "tok-b"
    assert stat.S_IMODE(os.stat(env.sys_creds).st_mode) == 0o600

    # CLI rotaciona os tokens de B no sistema.
    env.system(_creds("tok-b-renewed", "ref-b-renewed", "acc-b"))
    assert env.run("--switch-account", "codex", "a") == 0
    assert env.active_ids() == ["a"]
    assert _tok(pb / "auth.json") == "tok-b-renewed"

    assert env.run("--switch-account", "codex", "b") == 0
    assert _tok(env.sys_creds, "refresh_token") == "ref-b-renewed"
    assert env.active_ids() == ["b"]
    assert all("active" not in a for a in load_config(env.config)["agents"]["codex"]["accounts"])


def test_switch_with_legacy_default_loses_nothing(env):
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.system(_creds("tok-a", "ref-a", "acc-a"))
    env.save_cfg([_legacy(env), _acc("b", pb)])

    assert env.run("--switch-account", "codex", "b") == 0
    assert _tok(env.sys_creds) == "tok-b"
    default = next(a for a in load_config(env.config)["agents"]["codex"]["accounts"] if a["id"] == "default")
    assert _tok(Path(default["credential_path"])) == "tok-a"


def test_unknown_system_credential_is_captured_before_overwrite(env):
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_acc("b", pb)])
    env.system(_creds("tok-x", "ref-x", "acc-x", "x@x.com"))

    assert env.run("--switch-account", "codex", "b") == 0

    accs = load_config(env.config)["agents"]["codex"]["accounts"]
    assert len(accs) == 2
    new = next(a for a in accs if a["id"] != "b")
    assert _tok(Path(new["credential_path"])) == "tok-x"
    assert "x@x.com" in new["label"]
    assert _tok(env.sys_creds) == "tok-b"
    assert env.active_ids() == ["b"]


def test_failed_apply_rolls_back_system(env, monkeypatch, capsys):
    pa = env.profile("a", _creds("tok-a", "ref-a", "acc-a"))
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a", "acc-a"))
    before = env.sys_creds.read_bytes()

    def fail_on_system(provider, src, dst):
        if Path(dst).resolve() == env.sys_creds.resolve():
            assert _tok(env.sys_creds) == "tok-b"  # ja gravada: o rollback precisa desfazer
            raise OSError("disco cheio")

    monkeypatch.setattr(capture, "copy_identity_state", fail_on_system)
    capsys.readouterr()
    assert env.run("--switch-account", "codex", "b") == 1
    err = capsys.readouterr().err
    assert "disco cheio" in err
    assert env.sys_creds.read_bytes() == before
    assert "tok-" not in err


def test_switch_to_already_active_account_reports_it(env, capsys):
    pa = env.profile("a", _creds("tok-a", "ref-a", "acc-a"))
    env.save_cfg([_acc("a", pa)])
    env.system(_creds("tok-a-new", "ref-a-new", "acc-a"))
    assert env.run("--switch-account", "codex", "a") == 0
    assert _tok(env.sys_creds) == "tok-a-new"  # nao regrava tokens possivelmente rotacionados


def test_profile_with_newer_last_refresh_is_not_regressed_by_system(env):
    pa = env.profile("a", {**_creds("tok-a-new", "ref-a-new", "acc-a"), "last_refresh": "2026-05-02T00:00:00Z"})
    pb = env.profile("b", _creds("tok-b", "ref-b", "acc-b"))
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system({**_creds("tok-a-old", "ref-a-old", "acc-a"), "last_refresh": "2026-05-01T00:00:00Z"})

    assert env.run("--switch-account", "codex", "b") == 0
    assert _tok(pa / "auth.json", "refresh_token") == "ref-a-new"
    assert len(list(pa.glob("auth.json.bak-*"))) == 1


def test_non_string_account_id_and_email_are_ignored(tmp_path):
    f = tmp_path / "auth.json"
    save_secure_json({"tokens": {"access_token": "t", "account_id": 123, "id_token": _jwt({"email": 5})}}, f)
    assert credential_identity("codex", f) is None
