"""Identidade da Conta no Claude (ADR-0008): deteccao, migracao, fusao e troca pela CLI.

O caminho do sistema e redirecionado via CLAUDE_CONFIG_DIR para um diretorio temporario;
o arquivo de estado do Claude Code fica em $CLAUDE_CONFIG_DIR/.claude.json.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from ai_usage_collector import capture
from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config, save_config, save_secure_json


def _creds(access: str, refresh: str) -> dict:
    # O .credentials.json do Claude nao traz email nem accountId.
    return {"claudeAiOauth": {"accessToken": access, "refreshToken": refresh, "subscriptionType": "pro"}}


def _oauth(uuid: str, email: str) -> dict:
    return {"oauthAccount": {"accountUuid": uuid, "emailAddress": email}}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    sys_dir = tmp_path / "sys_claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(sys_dir))
    monkeypatch.delenv("CLAUDE_CREDENTIALS_PATH", raising=False)
    # Sem rede nos testes.
    monkeypatch.setattr("ai_usage_collector.extractors.claude.fetch_claude_usage_api", lambda *a, **k: None)

    class Env:
        root = tmp_path
        config = tmp_path / "cfg" / "config.json"
        cache = tmp_path / "status.json"
        sys_creds = sys_dir / ".credentials.json"
        sys_state = sys_dir / ".claude.json"

        def profile(self, name: str, creds: dict, uuid: str | None, email: str | None = None) -> Path:
            d = tmp_path / "cfg" / "profiles" / name
            save_secure_json(creds, d / ".credentials.json")
            if uuid:
                save_secure_json(_oauth(uuid, email or f"{name}@x.com"), d / ".claude.json")
            return d

        def system(self, creds: dict, uuid: str | None, email: str = "s@x.com", extra: dict | None = None):
            save_secure_json(creds, self.sys_creds)
            state = dict(extra or {})
            if uuid:
                state.update(_oauth(uuid, email))
            save_secure_json(state, self.sys_state)

        def save_cfg(self, accounts: list[dict]):
            save_config({"version": 1, "agents": {"claude": {"accounts": accounts},
                                                  "codex": {"accounts": []}, "gemini": {"accounts": []}}},
                        self.config)

        def run(self, *args: str) -> int:
            return main([*args, "--config-path", str(self.config), "--cache-path", str(self.cache)])

        def active_ids(self) -> list[str]:
            self.run("--status")
            accs = _read(self.cache)["agents"]["claude"]["accounts"]
            return [a["id"] for a in accs if a["isActive"]]

    return Env()


def _acc(acc_id: str, profile: Path, label: str | None = None, **extra) -> dict:
    return {"id": acc_id, "label": label or acc_id, "source": "captured",
            "credential_path": str(profile / ".credentials.json"), "claude_dir": str(profile), **extra}


def test_default_config_does_not_point_claude_to_system_path(env):
    cfg = load_config(env.config)
    assert cfg["agents"]["claude"]["accounts"] == []


def test_active_detected_by_identity_after_token_rotation(env):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb, active=True)])
    # CLI renovou access e refresh token da conta A no sistema.
    env.system(_creds("tok-a-rotated", "ref-a-rotated"), "uuid-a")

    assert env.active_ids() == ["a"]
    # Campo `active` nao e fonte de verdade.
    assert all("active" not in a for a in load_config(env.config)["agents"]["claude"]["accounts"])


def test_unknown_system_identity_marks_none_active(env):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    env.save_cfg([_acc("a", pa)])
    env.system(_creds("tok-a", "ref-a"), "uuid-other")
    assert env.active_ids() == []


def test_legacy_default_is_migrated_to_isolated_profile_idempotently(env):
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.system(_creds("tok-a", "ref-a"), "uuid-a", extra={"projects": {"x": 1}})
    env.save_cfg([
        {"id": "default", "label": "Claude (Padrão)", "source": "auto", "credential_path": str(env.sys_creds)},
        _acc("b", pb),
    ])

    cfg1 = load_config(env.config)
    accs = cfg1["agents"]["claude"]["accounts"]
    assert [a["id"] for a in accs] == ["default", "b"]
    migrated = Path(accs[0]["credential_path"])
    assert migrated.resolve() != env.sys_creds.resolve()
    assert _read(migrated)["claudeAiOauth"]["accessToken"] == "tok-a"
    assert _read(migrated.parent / ".claude.json")["oauthAccount"]["accountUuid"] == "uuid-a"
    assert stat.S_IMODE(os.stat(migrated).st_mode) == 0o600

    assert load_config(env.config) == cfg1  # idempotente
    assert env.active_ids() == ["default"]
    # Sistema intacto.
    assert _read(env.sys_creds)["claudeAiOauth"]["accessToken"] == "tok-a"


def test_legacy_default_without_system_credential_is_dropped(env):
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([
        {"id": "default", "label": "Claude (Padrão)", "source": "auto", "credential_path": str(env.sys_creds)},
        _acc("b", pb),
    ])
    assert [a["id"] for a in load_config(env.config)["agents"]["claude"]["accounts"]] == ["b"]


def test_legacy_default_merges_into_account_with_same_identity(env):
    pa = env.profile("a", _creds("tok-a-old", "ref-a-old"), "uuid-a")
    env.system(_creds("tok-a-new", "ref-a-new"), "uuid-a")
    env.save_cfg([
        {"id": "default", "label": "Claude (Padrão)", "source": "auto", "credential_path": str(env.sys_creds)},
        _acc("a", pa, label="Trabalho"),
    ])

    accs = load_config(env.config)["agents"]["claude"]["accounts"]
    assert [(a["id"], a["label"]) for a in accs] == [("a", "Trabalho")]
    # O backup trouxe a credencial mais recente do sistema para o Perfil Isolado.
    assert _read(pa / ".credentials.json")["claudeAiOauth"]["accessToken"] == "tok-a-new"


def test_duplicates_are_merged_preserving_renamed_label(env):
    p1 = env.profile("one", _creds("tok-1", "ref-1"), "uuid-a", "a@x.com")
    p2 = env.profile("two", _creds("tok-2", "ref-2"), "uuid-a", "a@x.com")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([
        _acc("one", p1, label="Claude (a@x.com)"),
        _acc("b", pb, label="Claude (pro)"),
        _acc("two", p2, label="Pessoal"),
    ])

    accs = load_config(env.config)["agents"]["claude"]["accounts"]
    labels = sorted(a["label"] for a in accs)
    assert labels == ["Claude (pro)", "Pessoal"]
    assert load_config(env.config)["agents"]["claude"]["accounts"] == accs  # idempotente
    # Perfil do duplicado nao e apagado (Perfil Orfao).
    assert (p1 / ".credentials.json").exists() and (p2 / ".credentials.json").exists()


def test_switch_a_b_a_preserves_renewed_tokens(env):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a", "a@x.com")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b", "b@x.com")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a"), "uuid-a", "a@x.com", extra={"projects": {"keep": True}})

    assert env.run("--switch-account", "claude", "b") == 0
    assert env.active_ids() == ["b"]
    assert _read(env.sys_creds)["claudeAiOauth"]["accessToken"] == "tok-b"
    assert _read(env.sys_state)["oauthAccount"]["accountUuid"] == "uuid-b"
    assert _read(env.sys_state)["projects"] == {"keep": True}
    assert stat.S_IMODE(os.stat(env.sys_creds).st_mode) == 0o600

    # CLI rotaciona os tokens de B no sistema.
    save_secure_json(_creds("tok-b-renewed", "ref-b-renewed"), env.sys_creds)
    assert env.run("--switch-account", "claude", "a") == 0
    assert env.active_ids() == ["a"]
    assert _read(pb / ".credentials.json")["claudeAiOauth"]["accessToken"] == "tok-b-renewed"

    assert env.run("--switch-account", "claude", "b") == 0
    assert _read(env.sys_creds)["claudeAiOauth"]["refreshToken"] == "ref-b-renewed"
    assert env.active_ids() == ["b"]
    assert all("active" not in a for a in load_config(env.config)["agents"]["claude"]["accounts"])


def test_unknown_system_credential_is_captured_before_overwrite(env):
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("b", pb)])
    env.system(_creds("tok-x", "ref-x"), "uuid-x", "x@x.com")

    assert env.run("--switch-account", "claude", "b") == 0

    accs = load_config(env.config)["agents"]["claude"]["accounts"]
    assert len(accs) == 2
    new = next(a for a in accs if a["id"] != "b")
    new_file = Path(new["credential_path"])
    assert _read(new_file)["claudeAiOauth"]["accessToken"] == "tok-x"
    assert _read(new_file.parent / ".claude.json")["oauthAccount"]["accountUuid"] == "uuid-x"
    assert "x@x.com" in new["label"]
    assert _read(env.sys_creds)["claudeAiOauth"]["accessToken"] == "tok-b"
    assert env.active_ids() == ["b"]


def test_failed_apply_rolls_back_system(env, monkeypatch, capsys):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a"), "uuid-a", extra={"projects": {"keep": True}})
    before = (env.sys_creds.read_bytes(), env.sys_state.read_bytes())

    real_copy = capture.copy_identity_state

    def fail_on_system(provider, src, dst):
        # Falha so na aplicacao (destino = sistema), depois de a credencial ja ter sido gravada.
        if Path(dst).resolve() == env.sys_creds.resolve():
            assert _read(env.sys_creds)["claudeAiOauth"]["accessToken"] == "tok-b"
            raise OSError("disco cheio")
        real_copy(provider, src, dst)

    monkeypatch.setattr(capture, "copy_identity_state", fail_on_system)
    capsys.readouterr()
    assert env.run("--switch-account", "claude", "b") == 1
    err = capsys.readouterr().err
    assert "disco cheio" in err
    assert (env.sys_creds.read_bytes(), env.sys_state.read_bytes()) == before
    assert "tok-" not in err  # nunca imprime segredos


def test_default_claude_dir_reads_identity_from_home_state_file(tmp_path, monkeypatch, capsys):
    """Sem CLAUDE_CONFIG_DIR, a identidade vem de ~/.claude.json (ao lado de ~/.claude)."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CREDENTIALS_PATH", raising=False)
    monkeypatch.setattr("ai_usage_collector.extractors.claude.fetch_claude_usage_api", lambda *a, **k: None)
    save_secure_json(_creds("tok-a", "ref-a"), home / ".claude" / ".credentials.json")
    (home / ".claude.json").write_text(json.dumps({**_oauth("uuid-a", "a@x.com"), "projects": {}}))
    os.chmod(home, 0o755)
    config = tmp_path / "cfg" / "config.json"
    save_config({"version": 1, "agents": {"claude": {"accounts": [
        {"id": "default", "label": "Claude (Padrão)", "source": "auto",
         "credential_path": "~/.claude/.credentials.json"}]}}}, config)

    assert main(["--status", "--config-path", str(config), "--cache-path", str(tmp_path / "s.json")]) == 0
    accs = json.loads(capsys.readouterr().out)["agents"]["claude"]["accounts"]
    assert [(a["id"], a["isActive"]) for a in accs] == [("default", True)]
    migrated = Path(load_config(config)["agents"]["claude"]["accounts"][0]["credential_path"])
    assert migrated.parent.parent == config.parent / "profiles"
    assert _read(migrated.parent / ".claude.json")["oauthAccount"]["accountUuid"] == "uuid-a"
    assert stat.S_IMODE(os.stat(home).st_mode) == 0o755  # $HOME nao tem permissoes alteradas
