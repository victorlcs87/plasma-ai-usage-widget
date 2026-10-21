"""Perfis Orfaos pela CLI (ticket 21, ADR-0008)."""

import json

from ai_usage_collector.cli import main
from ai_usage_collector.config import load_config


def make_profile(profiles, name, email, uuid, refresh="r1"):
    d = profiles / name
    d.mkdir(parents=True)
    (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "a-" + refresh, "refreshToken": refresh, "expiresAt": 1}}))
    (d / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": uuid, "emailAddress": email}}))
    return d


def setup(tmp_path):
    cfg = tmp_path / "cfg" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"agents": {"claude": {"accounts": []}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}))
    return cfg, tmp_path / "cfg" / "profiles", str(tmp_path / "status.json")


def run(cfg, cache, *args):
    return main([*args, "--config-path", str(cfg), "--cache-path", cache])


def test_list_and_status_expose_orphans(tmp_path, capsys):
    cfg, profiles, cache = setup(tmp_path)
    make_profile(profiles, "claude-a", "a@x.com", "uuid-a")
    assert run(cfg, cache, "--list-orphans") == 0
    out = json.loads(capsys.readouterr().out)
    assert [(o["provider"], o["id"], o["email"]) for o in out] == [("claude", "claude-a", "a@x.com")]
    run(cfg, cache, "--refresh")
    assert json.loads(open(cache).read())["orphan_profiles"][0]["id"] == "claude-a"


def test_referenced_profile_is_not_orphan(tmp_path, capsys):
    cfg, profiles, cache = setup(tmp_path)
    d = make_profile(profiles, "claude-a", "a@x.com", "uuid-a")
    c = json.loads(cfg.read_text())
    c["agents"]["claude"]["accounts"].append({"id": "claude-a", "credential_path": str(d / ".credentials.json"), "claude_dir": str(d)})
    cfg.write_text(json.dumps(c))
    run(cfg, cache, "--list-orphans")
    assert json.loads(capsys.readouterr().out) == []


def test_reimport_creates_account_keeping_profile(tmp_path):
    cfg, profiles, cache = setup(tmp_path)
    d = make_profile(profiles, "claude-a", "a@x.com", "uuid-a")
    assert run(cfg, cache, "--reimport-orphan", "claude", "claude-a") == 0
    accs = load_config(cfg)["agents"]["claude"]["accounts"]
    assert len(accs) == 1 and accs[0]["claude_dir"] == str(d) and "a@x.com" in accs[0]["label"]
    assert run(cfg, cache, "--list-orphans") == 0 and d.exists()


def test_reimport_merges_when_identity_exists(tmp_path):
    cfg, profiles, cache = setup(tmp_path)
    keep = make_profile(profiles, "claude-keep", "a@x.com", "uuid-a", refresh="old")
    c = json.loads(cfg.read_text())
    c["agents"]["claude"]["accounts"].append({"id": "claude-keep", "label": "Meu Trabalho", "name": "Meu Trabalho", "credential_path": str(keep / ".credentials.json"), "claude_dir": str(keep)})
    cfg.write_text(json.dumps(c))
    orphan = make_profile(profiles, "claude-dup", "a@x.com", "uuid-a", refresh="new")
    assert run(cfg, cache, "--reimport-orphan", "claude", "claude-dup") == 0
    accs = load_config(cfg)["agents"]["claude"]["accounts"]
    assert len(accs) == 1 and accs[0]["label"] == "Meu Trabalho"
    assert orphan.exists()  # fundir nunca apaga o orfao


def test_delete_requires_confirm(tmp_path, capsys):
    cfg, profiles, cache = setup(tmp_path)
    d = make_profile(profiles, "claude-a", "a@x.com", "uuid-a")
    assert run(cfg, cache, "--delete-orphan", "claude", "claude-a") == 1
    assert d.exists() and "--confirm" in capsys.readouterr().err
    assert run(cfg, cache, "--delete-orphan", "claude", "claude-a", "--confirm") == 0
    assert not d.exists()


def test_delete_refuses_registered_account_profile(tmp_path):
    cfg, profiles, cache = setup(tmp_path)
    d = make_profile(profiles, "claude-a", "a@x.com", "uuid-a")
    c = json.loads(cfg.read_text())
    c["agents"]["claude"]["accounts"].append({"id": "claude-a", "credential_path": str(d / ".credentials.json"), "claude_dir": str(d)})
    cfg.write_text(json.dumps(c))
    assert run(cfg, cache, "--delete-orphan", "claude", "claude-a", "--confirm") == 1
    assert d.exists()


def test_refresh_never_deletes_orphans(tmp_path):
    cfg, profiles, cache = setup(tmp_path)
    d = make_profile(profiles, "claude-a", "a@x.com", "uuid-a")
    run(cfg, cache, "--refresh")
    assert d.exists()


def test_symlink_or_outside_profile_is_not_orphan(tmp_path, capsys):  # M1
    cfg, profiles, cache = setup(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".credentials.json").write_text("{}")
    profiles.mkdir()
    (profiles / "link").symlink_to(outside)
    run(cfg, cache, "--list-orphans")
    assert json.loads(capsys.readouterr().out) == []


def test_merge_keeps_tokens_when_refresh_differs_and_orphan_not_newer(tmp_path, capsys):  # M2
    cfg, profiles, cache = setup(tmp_path)
    keep = make_profile(profiles, "claude-keep", "a@x.com", "uuid-a", refresh="old")
    c = json.loads(cfg.read_text())
    c["agents"]["claude"]["accounts"].append({"id": "claude-keep", "label": "K", "name": "K", "credential_path": str(keep / ".credentials.json"), "claude_dir": str(keep)})
    cfg.write_text(json.dumps(c))
    make_profile(profiles, "claude-dup", "a@x.com", "uuid-a", refresh="new")
    run(cfg, cache, "--reimport-orphan", "claude", "claude-dup")
    assert "mantidos" in capsys.readouterr().out
    assert json.loads((keep / ".credentials.json").read_text())["claudeAiOauth"]["refreshToken"] == "old"
