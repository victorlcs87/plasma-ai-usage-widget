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
    env.system(_creds("tok-other", "ref-other"), "uuid-other")
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


# --- Correcoes da revisao do ticket 18 ------------------------------------------------


def _legacy_default(env) -> dict:
    return {"id": "default", "label": "Claude (Padrão)", "source": "auto", "credential_path": str(env.sys_creds)}


def _baks(profile: Path) -> list[Path]:
    return sorted(profile.glob(".credentials.json.bak-*"))


def test_activating_already_active_account_keeps_fresh_tokens(env):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a-newer", "ref-a-newer"), "uuid-a")

    assert env.run("--switch-account", "claude", "a") == 0
    assert _read(env.sys_creds)["claudeAiOauth"]["refreshToken"] == "ref-a-newer"
    assert _read(pa / ".credentials.json")["claudeAiOauth"]["refreshToken"] == "ref-a-newer"
    assert env.active_ids() == ["a"]

    assert env.run("--switch-account", "claude", "b") == 0
    assert _read(pa / ".credentials.json")["claudeAiOauth"]["refreshToken"] == "ref-a-newer"


def test_exact_token_match_prevails_over_stale_identity(env):
    # ~/.claude.json defasado diz A, mas a credencial do sistema e exatamente a de B.
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_legacy_default(env), _acc("a", pa, label="A"), _acc("b", pb, label="B")])
    env.system(_creds("tok-b", "ref-b"), "uuid-a")

    accs = load_config(env.config)["agents"]["claude"]["accounts"]
    assert [(a["id"], a["label"]) for a in accs] == [("a", "A"), ("b", "B")]
    assert _read(pa / ".credentials.json")["claudeAiOauth"]["refreshToken"] == "ref-a"
    assert _baks(pa) == []


def test_stale_identity_never_loses_profile_credential(env):
    # Cenario s3: identidade defasada (A) e tokens rotacionados de B; nada coincide por token.
    pa = env.profile("a", _creds("tok-a-old", "ref-a-old"), "uuid-a")
    pb = env.profile("b", _creds("tok-b-old", "ref-b-old"), "uuid-b")
    env.save_cfg([_legacy_default(env), _acc("a", pa, label="A"), _acc("b", pb, label="B")])
    env.system(_creds("tok-b-new", "ref-b-new"), "uuid-a")

    load_config(env.config)
    baks = _baks(pa)
    assert len(baks) == 1
    assert _read(baks[0])["claudeAiOauth"]["refreshToken"] == "ref-a-old"
    assert stat.S_IMODE(os.stat(baks[0]).st_mode) == 0o600


def test_profile_backups_keep_only_last_three(env):
    pa = env.profile("a", _creds("tok-0", "ref-0"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    for i in range(1, 6):
        env.system(_creds(f"tok-{i}", f"ref-{i}"), "uuid-a")
        assert env.run("--switch-account", "claude", "b") == 0
        assert env.run("--switch-account", "claude", "a") == 0
    assert len(_baks(pa)) == 3


def test_legacy_default_merges_by_tokens_into_profiles_without_identity(env):
    # Layout real: perfis capturados antes do ticket (sem .claude.json); sistema == tokens da cga.
    ps = env.profile("claude-signatus", _creds("tok-s", "ref-s"), None)
    pc = env.profile("claude-cga", _creds("tok-c", "ref-c"), None)
    env.save_cfg([_legacy_default(env), _acc("claude-signatus", ps, label="Claude (signatus)"),
                  _acc("claude-cga", pc, label="CGA")])
    env.system(_creds("tok-c", "ref-c"), "uuid-cga", "cga@x.com")

    cfg = load_config(env.config)
    accs = cfg["agents"]["claude"]["accounts"]
    assert [(a["id"], a["label"]) for a in accs] == [("claude-signatus", "Claude (signatus)"), ("claude-cga", "CGA")]
    assert _read(pc / ".claude.json")["oauthAccount"]["accountUuid"] == "uuid-cga"
    assert not (ps / ".claude.json").exists()
    assert load_config(env.config) == cfg
    assert env.active_ids() == ["claude-cga"]


def test_unmatched_legacy_default_gets_email_label(env):
    env.system(_creds("tok-x", "ref-x"), "uuid-x", "x@x.com")
    env.save_cfg([_legacy_default(env)])
    accs = load_config(env.config)["agents"]["claude"]["accounts"]
    assert [(a["id"], a["label"], a["name"]) for a in accs] == [("default", "Claude (x@x.com)", "Claude (x@x.com)")]


def test_user_typed_label_like_auto_format_is_preserved_on_merge(env):
    p1 = env.profile("one", _creds("tok-1", "ref-1"), "uuid-a", "a@x.com")
    p2 = env.profile("two", _creds("tok-2", "ref-2"), "uuid-a", "a@x.com")
    env.save_cfg([_acc("one", p1, label="Claude (a@x.com)"), _acc("two", p2, label="Claude (signatus)")])
    accs = load_config(env.config)["agents"]["claude"]["accounts"]
    assert [a["label"] for a in accs] == ["Claude (signatus)"]


def test_unreadable_state_file_aborts_switch(env, capsys):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a"), "uuid-a")
    env.sys_state.write_text('{"projects": {"real": 1}, "oauthAccount": {"accountUuid": "uuid-a"')
    before = (env.sys_creds.read_bytes(), env.sys_state.read_bytes())

    assert env.run("--switch-account", "claude", "b") == 1
    assert (env.sys_creds.read_bytes(), env.sys_state.read_bytes()) == before


def test_state_file_overwritten_during_write_rolls_back(env, monkeypatch, capsys):
    from ai_usage_collector import identity

    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a"), "uuid-a", extra={"projects": {"keep": True}})
    before = (env.sys_creds.read_bytes(), env.sys_state.read_bytes())
    real_replace = os.replace
    raced = []

    def racing_replace(src, dst):
        real_replace(src, dst)
        if Path(dst) == env.sys_state.resolve() and not raced:
            raced.append(True)
            Path(dst).write_text('{"concurrent": true}')  # Claude Code regravou logo em seguida

    monkeypatch.setattr(identity.os, "replace", racing_replace)
    capsys.readouterr()
    assert env.run("--switch-account", "claude", "b") == 1
    assert "alterado" in capsys.readouterr().err
    monkeypatch.setattr(identity.os, "replace", real_replace)
    assert (env.sys_creds.read_bytes(), env.sys_state.read_bytes()) == before


def test_rollback_failure_is_reported(env, monkeypatch, capsys):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    env.system(_creds("tok-a", "ref-a"), "uuid-a")
    real_copy = capture.copy_identity_state

    def fail_on_system(provider, src, dst):
        if Path(dst).resolve() == env.sys_creds.resolve():
            raise OSError("disco cheio")
        real_copy(provider, src, dst)

    class BrokenTempfile:
        @staticmethod
        def mkstemp(*a, **k):
            raise OSError("sem espaco")

    monkeypatch.setattr(capture, "copy_identity_state", fail_on_system)
    monkeypatch.setattr(capture, "tempfile", BrokenTempfile)
    capsys.readouterr()
    assert env.run("--switch-account", "claude", "b") == 1
    err = capsys.readouterr().err
    assert "restaurar" in err and "restaurado" not in err


def test_symlinked_state_and_credentials_are_preserved(env):
    pa = env.profile("a", _creds("tok-a", "ref-a"), "uuid-a")
    pb = env.profile("b", _creds("tok-b", "ref-b"), "uuid-b")
    env.save_cfg([_acc("a", pa), _acc("b", pb)])
    real_dir = env.root / "dotfiles"
    save_secure_json(_creds("tok-a", "ref-a"), real_dir / "credentials.json")
    save_secure_json({**_oauth("uuid-a", "a@x.com"), "projects": {}}, real_dir / "claude.json")
    env.sys_creds.parent.mkdir(parents=True, exist_ok=True)
    env.sys_creds.symlink_to(real_dir / "credentials.json")
    env.sys_state.symlink_to(real_dir / "claude.json")

    assert env.run("--switch-account", "claude", "b") == 0
    assert env.sys_creds.is_symlink() and env.sys_state.is_symlink()
    assert _read(real_dir / "credentials.json")["claudeAiOauth"]["accessToken"] == "tok-b"
    assert _read(real_dir / "claude.json")["oauthAccount"]["accountUuid"] == "uuid-b"


def test_failed_migration_save_keeps_load_working_without_new_orphans(env, monkeypatch):
    env.system(_creds("tok-x", "ref-x"), "uuid-x", "x@x.com")
    env.save_cfg([_legacy_default(env)])

    def fail(*a, **k):
        raise OSError("somente leitura")

    monkeypatch.setattr(capture, "save_config", fail)
    profiles = env.config.parent / "profiles"
    for _ in range(2):
        cfg = load_config(env.config)
        assert cfg["agents"]["claude"]["accounts"][0]["credential_path"] == str(env.sys_creds)
    assert not profiles.exists() or list(profiles.iterdir()) == []
