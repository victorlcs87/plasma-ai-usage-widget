"""Historico de Tokens: leitura incremental, retencao, contrato e exportacao pela CLI."""

import csv
import io
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config
from ai_usage_collector.contract import validate_status_contract


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr("ai_usage_collector.extractors.claude.fetch_claude_usage_api", lambda *a, **k: None)
    monkeypatch.setattr("ai_usage_collector.extractors.codex.fetch_codex_usage_api", lambda *a, **k: None)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _local_day(dt):
    return datetime.fromtimestamp(dt.timestamp()).date().isoformat()


def _claude_line(dt, msg_id, inp, out, model="claude-sonnet-4-5"):
    return json.dumps({
        "type": "assistant",
        "timestamp": _iso(dt),
        "requestId": f"req_{msg_id}",
        "message": {"id": msg_id, "model": model, "usage": {"input_tokens": inp, "output_tokens": out}},
    }) + "\n"


def _codex_lines(dt, model, turns):
    lines = [json.dumps({"timestamp": _iso(dt), "type": "turn_context", "payload": {"model": model}}) + "\n"]
    total = 0
    for inp, out in turns:
        total += inp + out
        ev = {"timestamp": _iso(dt), "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"total_tokens": total},
            "last_token_usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out},
        }}}
        lines.append(json.dumps(ev) + "\n")
        lines.append(json.dumps(ev) + "\n")  # Codex repete o evento; nao pode contar duas vezes
    return "".join(lines)


def _setup(tmp_path):
    claude_dir = tmp_path / "profile_claude"
    codex_dir = tmp_path / "profile_codex"
    (claude_dir / "projects" / "proj").mkdir(parents=True)
    (codex_dir / "sessions" / "2026" / "10" / "20").mkdir(parents=True)
    cfg = {
        "version": 1,
        "agents": {
            "claude": {"accounts": [{"id": "claude-a", "label": "A", "source": "manual", "claude_dir": str(claude_dir)}]},
            "codex": {"accounts": [{"id": "codex-a", "label": "C", "source": "manual", "codex_dir": str(codex_dir)}]},
            "gemini": {"accounts": []},
        },
    }
    config_path = tmp_path / "config.json"
    save_config(cfg, config_path)
    return claude_dir, codex_dir, config_path, tmp_path / "cache" / "status.json"


def _refresh(config_path, cache_path):
    assert main(["--refresh", "--config-path", str(config_path), "--cache-path", str(cache_path)]) == 0
    return json.loads(cache_path.read_text())


def _acc(status, provider):
    return status["agents"][provider]["accounts"][0]


def test_incremental_read_does_not_duplicate_and_appends(tmp_path):
    claude_dir, codex_dir, config_path, cache_path = _setup(tmp_path)
    now = datetime.now(timezone.utc)
    log = claude_dir / "projects" / "proj" / "s1.jsonl"
    # Mesma mensagem em duas linhas consecutivas (blocos de conteudo): conta uma vez
    log.write_text(_claude_line(now, "m1", 100, 50) + _claude_line(now, "m1", 100, 50) + _claude_line(now, "m2", 10, 5))
    (codex_dir / "sessions" / "2026" / "10" / "20" / "rollout-x.jsonl").write_text(
        _codex_lines(now, "gpt-5-codex", [(1000, 200), (300, 30)])
    )

    status = _refresh(config_path, cache_path)
    assert validate_status_contract(status) is True
    th = _acc(status, "claude")["token_history"]
    assert th["today"] == 165
    assert th["week"] == 165 and th["month"] == 165
    assert len(th["daily_30d"]) == 30 and th["daily_30d"][-1] == {"date": _local_day(now), "tokens": 165}
    assert len(th["weekly_3m"]) == 13 and th["weekly_3m"][-1]["tokens"] == 165
    assert len(th["monthly_12m"]) == 12 and th["monthly_12m"][-1]["tokens"] == 165
    assert _acc(status, "codex")["token_history"]["today"] == 1530

    # Reexecutar nao duplica
    status = _refresh(config_path, cache_path)
    assert _acc(status, "claude")["token_history"]["today"] == 165
    assert _acc(status, "codex")["token_history"]["today"] == 1530

    # Linha nova (e uma linha parcial ainda sendo escrita) entra so uma vez
    with open(log, "a") as f:
        f.write(_claude_line(now, "m3", 1, 1))
        f.write('{"type": "assistant", "timestamp"')
    status = _refresh(config_path, cache_path)
    assert _acc(status, "claude")["token_history"]["today"] == 167
    rest = json.dumps(_iso(now)) + ', "requestId": "r4", "message": {"id": "m4", "usage": {"input_tokens": 2, "output_tokens": 1}}}\n'
    with open(log, "a") as f:  # a linha parcial e completada e conta uma vez
        f.write(": " + rest)
    _refresh(config_path, cache_path)
    status = _refresh(config_path, cache_path)
    assert _acc(status, "claude")["token_history"]["today"] == 170

    # Sessao retomada copia mensagens antigas para outro arquivo: nao conta de novo
    (claude_dir / "projects" / "proj" / "s2.jsonl").write_text(_claude_line(now, "m1", 100, 50) + _claude_line(now, "m5", 1, 0))
    status = _refresh(config_path, cache_path)
    assert _acc(status, "claude")["token_history"]["today"] == 171

    history_file = cache_path.parent / "history.json"
    assert stat.S_IMODE(os.stat(history_file).st_mode) == 0o600


def test_retention_and_persistence_after_logs_deleted(tmp_path):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    now = datetime.now(timezone.utc)
    log = claude_dir / "projects" / "proj" / "s1.jsonl"
    log.write_text(_claude_line(now - timedelta(days=10), "old", 400, 100) + _claude_line(now, "new", 7, 3))
    cache_path.parent.mkdir(parents=True)
    ancient = (now - timedelta(days=420)).date().isoformat()
    (cache_path.parent / "history.json").write_text(json.dumps({
        "version": 1, "cursors": {},
        "daily": {ancient: {"claude": {"claude-a": {"m": 999}}}},
    }))

    _refresh(config_path, cache_path)
    log.unlink()  # o CLI apagou os logs antigos
    status = _refresh(config_path, cache_path)

    th = _acc(status, "claude")["token_history"]
    assert th["today"] == 10
    assert sum(d["tokens"] for d in th["daily_30d"]) == 510
    history = json.loads((cache_path.parent / "history.json").read_text())
    assert ancient not in history["daily"]
    assert all(str(log) != p for p in history["cursors"])


def test_system_logs_attributed_to_active_account(tmp_path, monkeypatch):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    creds = {"claudeAiOauth": {"accessToken": "tok-a", "refreshToken": "ref-a", "expiresAt": 4102444800000}}
    (claude_dir / ".credentials.json").write_text(json.dumps(creds))
    sys_dir = tmp_path / "_sys_claude"
    (sys_dir / "projects" / "p").mkdir(parents=True)
    (sys_dir / ".credentials.json").write_text(json.dumps(creds))
    now = datetime.now(timezone.utc)
    (sys_dir / "projects" / "p" / "s.jsonl").write_text(_claude_line(now, "sys1", 20, 2))

    status = _refresh(config_path, cache_path)
    acc = _acc(status, "claude")
    assert acc["isActive"] is True
    assert acc["token_history"]["today"] == 22


def test_export_history_csv_and_json(tmp_path, capsys):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    now = datetime.now(timezone.utc)
    (claude_dir / "projects" / "proj" / "s1.jsonl").write_text(
        _claude_line(now, "m1", 100, 50, model="opus") + _claude_line(now, "m2", 1, 1, model="haiku")
    )
    _refresh(config_path, cache_path)
    capsys.readouterr()

    base = ["--config-path", str(config_path), "--cache-path", str(cache_path)]
    assert main(["--export-history", "csv", *base]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    day = _local_day(now)
    assert {"date": day, "provider": "claude", "account": "claude-a", "model": "opus", "tokens": "150"} in rows
    assert {"date": day, "provider": "claude", "account": "claude-a", "model": "haiku", "tokens": "2"} in rows

    assert main(["--export-history", "json", *base]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"date": day, "provider": "claude", "account": "claude-a", "model": "opus", "tokens": 150} in data


def test_corrupted_history_is_preserved_and_status_still_saved(tmp_path, capsys):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    (claude_dir / "projects" / "proj" / "s1.jsonl").write_text(_claude_line(datetime.now(timezone.utc), "m1", 1, 1))
    cache_path.parent.mkdir(parents=True)
    history_file = cache_path.parent / "history.json"
    history_file.write_text("{corrompido")

    status = _refresh(config_path, cache_path)
    assert "token_history" not in _acc(status, "claude")
    assert history_file.read_text() == "{corrompido"
    assert "Historico de Tokens" in capsys.readouterr().err


def test_summary_period_boundaries():
    from datetime import date

    from ai_usage_collector.history import summarize

    # 2026-10-21 e quarta-feira; a semana comeca na segunda 2026-10-19
    days = {"2026-10-18": 1, "2026-10-19": 10, "2026-10-21": 100, "2026-09-30": 1000, "2025-10-31": 5, "2025-11-01": 7}
    history = {"daily": {d: {"claude": {"a": {"m": t}}} for d, t in days.items()}}
    s = summarize(history, "claude", "a", date(2026, 10, 21))
    assert (s["today"], s["week"], s["month"]) == (100, 110, 111)
    assert s["weekly_3m"][-1] == {"week_start": "2026-10-19", "tokens": 110}
    assert s["weekly_3m"][-2] == {"week_start": "2026-10-12", "tokens": 1}
    assert s["monthly_12m"][0] == {"month": "2025-11", "tokens": 7}
    assert s["monthly_12m"][-2] == {"month": "2026-09", "tokens": 1000}
    assert summarize(history, "claude", "outra", date(2026, 10, 21))["month"] == 0


def test_status_without_history_field_still_valid():
    from ai_usage_collector.contract import build_empty_status_contract

    payload = build_empty_status_contract()
    assert payload["version"] == 5
    assert validate_status_contract(payload) is True
    payload["version"] = 1  # contratos antigos continuam aceitos
    assert validate_status_contract(payload) is True


# --- Historico por Identidade da Conta (ticket 42) ---------------------------


def _claude_world(tmp_path, monkeypatch):
    """Sistema em CLAUDE_CONFIG_DIR (conftest); duas Contas com identidades uuid-a e uuid-b."""
    from ai_usage_collector.config import save_secure_json

    sys_dir = tmp_path / "_sys_claude"
    accs = []
    for name in ("a", "b"):
        d = tmp_path / "cfg" / "profiles" / name
        save_secure_json({"claudeAiOauth": {"accessToken": f"tok-{name}", "refreshToken": f"ref-{name}"}}, d / ".credentials.json")
        save_secure_json({"oauthAccount": {"accountUuid": f"uuid-{name}", "emailAddress": f"{name}@x.com"}}, d / ".claude.json")
        accs.append({"id": name, "label": name, "source": "captured",
                     "credential_path": str(d / ".credentials.json"), "claude_dir": str(d)})
    cfg = {"version": 1, "agents": {"claude": {"accounts": accs}, "codex": {"accounts": []}, "gemini": {"accounts": []}}}
    config_path = tmp_path / "cfg" / "config.json"
    save_config(cfg, config_path)
    save_secure_json({"claudeAiOauth": {"accessToken": "tok-a", "refreshToken": "ref-a"}}, sys_dir / ".credentials.json")
    save_secure_json({"oauthAccount": {"accountUuid": "uuid-a", "emailAddress": "a@x.com"}}, sys_dir / ".claude.json")
    (sys_dir / "projects" / "p").mkdir(parents=True)
    return sys_dir / "projects" / "p" / "s.jsonl", config_path, tmp_path / "cache" / "status.json"


def _acc_by_id(status, acc_id):
    return next(a for a in status["agents"]["claude"]["accounts"] if a["id"] == acc_id)


def test_switch_attributes_system_logs_to_outgoing_identity(tmp_path, monkeypatch):
    log, config_path, cache_path = _claude_world(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    base = ["--config-path", str(config_path), "--cache-path", str(cache_path)]

    log.write_text(_claude_line(now, "m1", 100, 0))  # consumo de A
    assert main(["--switch-account", "claude", "b", *base]) == 0
    with open(log, "a") as f:
        f.write(_claude_line(now, "m2", 20, 0))  # consumo de B
    assert main(["--switch-account", "claude", "a", *base]) == 0
    with open(log, "a") as f:
        f.write(_claude_line(now, "m3", 3, 0))  # consumo de A de novo

    status = _refresh(config_path, cache_path)
    assert _acc_by_id(status, "a")["token_history"]["today"] == 103
    assert _acc_by_id(status, "b")["token_history"]["today"] == 20


def test_history_follows_identity_on_rename_and_converts_v1(tmp_path, monkeypatch):
    log, config_path, cache_path = _claude_world(tmp_path, monkeypatch)
    cache_path.parent.mkdir(parents=True)
    day = _local_day(datetime.now(timezone.utc))
    # v1: por id da Conta; "a" duplicada com outro id (mesma identidade) e "sistema" sem dono
    cfg = json.loads(config_path.read_text())
    from ai_usage_collector.config import save_secure_json

    d = tmp_path / "cfg" / "profiles" / "a-old"  # mesma identidade, tokens divergentes: a fusao automatica nao a remove
    save_secure_json({"claudeAiOauth": {"accessToken": "tok-old", "refreshToken": "ref-old"}}, d / ".credentials.json")
    save_secure_json({"oauthAccount": {"accountUuid": "uuid-a", "emailAddress": "a@x.com"}}, d / ".claude.json")
    dup = dict(cfg["agents"]["claude"]["accounts"][0], id="a-old", credential_path=str(d / ".credentials.json"), claude_dir=str(d))
    cfg["agents"]["claude"]["accounts"].append(dup)
    save_config(cfg, config_path)
    (cache_path.parent / "history.json").write_text(json.dumps({
        "version": 1, "cursors": {},
        "daily": {day: {"claude": {"a": {"m": 10}, "a-old": {"m": 5}, "b": {"m": 7}, "sistema": {"m": 1}}}},
    }))

    for _ in range(2):  # idempotente
        status = _refresh(config_path, cache_path)
        assert _acc_by_id(status, "b")["token_history"]["today"] == 7
        th = _acc_by_id(status, "a")["token_history"]
        assert th["today"] == 16  # 10 + 5 + 1 (sistema -> identidade ativa), sem duplicar
        assert th["estimated"] is True
        assert _acc_by_id(status, "b")["token_history"]["estimated"] is False

    # Renomear nao perde historico
    cfg = json.loads(config_path.read_text())
    cfg["agents"]["claude"]["accounts"][0]["label"] = "Novo nome"
    save_config(cfg, config_path)
    assert _acc_by_id(_refresh(config_path, cache_path), "a")["token_history"]["today"] == 16


def test_first_system_read_is_estimated(tmp_path, monkeypatch):
    log, config_path, cache_path = _claude_world(tmp_path, monkeypatch)
    log.write_text(_claude_line(datetime.now(timezone.utc), "m1", 9, 0))
    status = _refresh(config_path, cache_path)
    th = _acc_by_id(status, "a")["token_history"]
    assert (th["today"], th["estimated"]) == (9, True)


# --- Revisao do ticket 42 ----------------------------------------------------


def test_tokens_read_before_identity_known_still_shown_after(tmp_path, monkeypatch):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    now = datetime.now(timezone.utc)
    (claude_dir / "projects" / "proj" / "s.jsonl").write_text(_claude_line(now, "m1", 10, 0))
    assert _acc(_refresh(config_path, cache_path), "claude")["token_history"]["today"] == 10
    from ai_usage_collector.config import save_secure_json
    save_secure_json({"oauthAccount": {"accountUuid": "uuid-z", "emailAddress": "z@x.com"}}, claude_dir / ".claude.json")
    save_secure_json({"claudeAiOauth": {"accessToken": "t", "refreshToken": "r"}}, claude_dir / ".credentials.json")
    with open(claude_dir / "projects" / "proj" / "s.jsonl", "a") as f:
        f.write(_claude_line(now, "m2", 5, 0))
    assert _acc(_refresh(config_path, cache_path), "claude")["token_history"]["today"] == 15


def test_v1_system_bucket_without_active_identity_stays_pending(tmp_path):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    cache_path.parent.mkdir(parents=True)
    day = _local_day(datetime.now(timezone.utc))
    hist = cache_path.parent / "history.json"
    hist.write_text(json.dumps({"version": 1, "cursors": {}, "daily": {day: {"claude": {"sistema": {"m": 4}}}}}))
    _refresh(config_path, cache_path)
    data = json.loads(hist.read_text())
    assert data["version"] == 1 and data["daily"][day]["claude"]["sistema"] == {"m": 4}


def test_invalid_token_counts_do_not_abort_history(tmp_path):
    claude_dir, _, config_path, cache_path = _setup(tmp_path)
    now = datetime.now(timezone.utc)
    bad = json.loads(_claude_line(now, "bad", 0, 0))
    bad["message"]["usage"]["input_tokens"] = "abc"
    (claude_dir / "projects" / "proj" / "s.jsonl").write_text(json.dumps(bad) + "\n" + _claude_line(now, "ok", 7, 0))
    assert _acc(_refresh(config_path, cache_path), "claude")["token_history"]["today"] == 7


@pytest.mark.parametrize("version", ['"2"', "null", "99"])
def test_bad_or_newer_history_version_is_never_overwritten(tmp_path, capsys, version):
    _, _, config_path, cache_path = _setup(tmp_path)
    cache_path.parent.mkdir(parents=True)
    hist = cache_path.parent / "history.json"
    raw = '{"version": %s, "daily": {}}' % version
    hist.write_text(raw)
    status = _refresh(config_path, cache_path)
    assert "token_history" not in _acc(status, "claude")
    assert hist.read_text() == raw
    assert "Historico de Tokens" in capsys.readouterr().err


def test_export_masks_identities_without_account(tmp_path, capsys):
    _, _, config_path, cache_path = _setup(tmp_path)
    cache_path.parent.mkdir(parents=True)
    day = _local_day(datetime.now(timezone.utc))
    (cache_path.parent / "history.json").write_text(json.dumps({
        "version": 2, "cursors": {}, "daily": {day: {"claude": {"email:gone@x.com": {"m": 1}}}}}))
    assert main(["--export-history", "csv", "--config-path", str(config_path), "--cache-path", str(cache_path)]) == 0
    out = capsys.readouterr().out
    assert "gone@x.com" not in out and "(conta removida)" in out
