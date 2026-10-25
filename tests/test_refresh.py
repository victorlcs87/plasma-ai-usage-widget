"""Atualizacao periodica por provedor (ADR-0007): 429/retry-after, backoff, cache desatualizado."""

import http.client
import json
import os
import stat
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from ai_usage_collector import refresh
from ai_usage_collector.cli import main
from ai_usage_collector.config import save_config

T0 = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)

PROVIDER_URLS = {
    "claude": "api.anthropic.com",
    "codex": "chatgpt.com",
    "gemini": "cloudcode-pa.googleapis.com",
}

API_OK = {
    "claude": {"five_hour": {"utilization": 42.0}, "seven_day": {"utilization": 10.0}},
    "codex": {"rate_limit": {"primary_window": {"used_percent": 42.0}, "secondary_window": {"used_percent": 10.0}}},
    "gemini": {"buckets": [{"bucketId": "gemini-5h", "remainingFraction": 0.58}]},
}


class FakeResp:
    status = 200

    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self, amt=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("https://x", code, "err", headers, None)


class FakeHttp:
    """urlopen simulado: cada provedor responde com a proxima resposta da sua fila (ou a ultima)."""

    def __init__(self, **responses):
        self.responses = responses
        self.calls = {p: 0 for p in PROVIDER_URLS}
        self.urls: list[str] = []

    def __call__(self, req, timeout=None):
        prov = next(p for p, host in PROVIDER_URLS.items() if host in req.full_url)
        self.urls.append(req.full_url)
        queue = self.responses[prov]
        if prov == "gemini" and req.full_url.endswith(":retrieveUserQuota") and "gemini_models" in self.responses:
            queue = self.responses["gemini_models"]  # fila propria do endpoint de cota por modelo
            resp = queue[min(sum(u.endswith(":retrieveUserQuota") for u in self.urls) - 1, len(queue) - 1)]
            self.calls[prov] += 1
            if isinstance(resp, Exception):
                raise resp
            return FakeResp(resp)
        resp = queue[min(self.calls[prov], len(queue) - 1)]
        self.calls[prov] += 1
        if isinstance(resp, Exception):
            raise resp
        return FakeResp(resp)


def make_profile(tmp_path, provider, name, token="tok-1", expired=False, ident=None):
    """Perfil isolado sem historico local, com credencial valida (ou vencida ha 40 h com `expired`).

    `ident` grava a Identidade da Conta (uuid no Claude, account_id no Codex, email no Gemini)."""
    d = tmp_path / "profiles" / provider / name
    d.mkdir(parents=True)
    # `expired`: True = venceu ha 40 h; timedelta = validade relativa a T0 (ex.: +30 min = vence antes do proximo Intervalo)
    exp = T0 + (expired if isinstance(expired, timedelta) else -timedelta(hours=40)) if expired else T0 + timedelta(days=5)
    if provider == "claude":
        cred = d / ".credentials.json"
        cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": exp.isoformat()}}))
        if ident:
            (d / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": ident}}))
        return {"id": name, "label": name, "claude_dir": str(d), "credential_path": str(cred)}
    if provider == "codex":
        cred = d / "auth.json"
        tokens = {"access_token": token, "account_id": ident or "acc"}
        cred.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": tokens}))
        return {"id": name, "label": name, "codex_dir": str(d), "credential_path": str(cred)}
    cred = d / "oauth_creds.json"
    data = {"access_token": token, "refresh_token": "r", "expiry_date": int(exp.timestamp() * 1000)}
    if ident:
        data["email"] = ident
    cred.write_text(json.dumps(data))
    return {"id": name, "label": name, "gemini_dir": str(d), "credential_path": str(cred)}


def make_expired_profile(tmp_path, provider, name, **kw):
    return make_profile(tmp_path, provider, name, expired=True, **kw)


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = {"now": T0}
    monkeypatch.setattr(refresh, "utcnow", lambda: clock["now"])
    paths = {"config": tmp_path / "config.json", "cache": tmp_path / "cache" / "status.json", "clock": clock}

    def run(*args, http):
        monkeypatch.setattr("urllib.request.urlopen", http)
        monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda _self, req, timeout=None: http(req, timeout))
        rc = main(["--config-path", str(paths["config"]), "--cache-path", str(paths["cache"]), "--refresh", *args])
        assert rc == 0
        return json.loads(paths["cache"].read_text())

    paths["run"] = run
    return paths


def configure(env, tmp_path, accounts_by_provider):
    save_config({"version": 1, "renew": {"gemini": True}, "agents": {p: {"accounts": accs} for p, accs in accounts_by_provider.items()}}, env["config"])


def acc_of(status, provider, idx=0):
    return status["agents"][provider]["accounts"][idx]


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini"])
def test_429_without_cache_yields_no_data_never_invented_zero(env, tmp_path, provider):
    configure(env, tmp_path, {provider: [make_profile(tmp_path, provider, "a")]})
    http = FakeHttp(**{provider: [http_error(429, "226")]})

    status = env["run"]("--provider", provider, http=http)

    acc = acc_of(status, provider)
    assert acc["no_data"] is True
    assert acc["stale"] is True
    assert acc["fetch_error"]["kind"] == "rate_limited"
    assert "limite de requisi" in acc["fetch_error"]["message"].lower()
    retry_at = datetime.fromisoformat(acc["fetch_error"]["retry_at"])
    assert retry_at == T0 + timedelta(seconds=226)
    assert datetime.fromisoformat(acc["next_check_at"]) >= retry_at
    assert acc["native_window"]["release_time"] is None
    assert "fetched_at" not in acc


def test_pause_is_respected_until_retry_after_even_on_refresh_now(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    http = FakeHttp(claude=[http_error(429, "226"), API_OK["claude"]])
    env["run"]("--provider", "claude", http=http)

    env["clock"]["now"] = T0 + timedelta(seconds=100)
    status = env["run"](http=http)  # "Atualizar agora": todos os provedores
    assert http.calls["claude"] == 1
    assert acc_of(status, "claude")["fetch_error"]["kind"] == "rate_limited"

    env["clock"]["now"] = T0 + timedelta(seconds=227)
    status = env["run"]("--provider", "claude", http=http)
    assert http.calls["claude"] == 2
    acc = acc_of(status, "claude")
    assert acc["stale"] is False
    assert acc["native_window"]["usage_percentage"] == 42.0
    assert "fetch_error" not in acc and "no_data" not in acc


def test_429_serves_last_valid_result_marked_stale(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    http = FakeHttp(claude=[API_OK["claude"], http_error(429, "30")])
    first = env["run"]("--provider", "claude", "--refresh-interval", "claude=3600", http=http)
    acc = acc_of(first, "claude")
    assert acc["stale"] is False
    assert acc["fetched_at"] == T0.isoformat()
    assert acc["next_check_at"] == (T0 + timedelta(seconds=3600)).isoformat()
    assert first["agents"]["claude"]["fetched_at"] == T0.isoformat()

    env["clock"]["now"] = T0 + timedelta(seconds=3600)
    second = env["run"]("--provider", "claude", http=http)
    acc = acc_of(second, "claude")
    assert acc["stale"] is True
    assert acc["fetched_at"] == T0.isoformat()
    assert acc["native_window"]["usage_percentage"] == 42.0
    assert acc["weekly_window"]["usage_percentage"] == 10.0
    assert "no_data" not in acc
    assert second["agents"]["claude"]["stale"] is True


def test_exponential_backoff_when_retry_after_absent(env, tmp_path):
    configure(env, tmp_path, {"codex": [make_profile(tmp_path, "codex", "a")]})
    http = FakeHttp(codex=[http_error(429)])
    s1 = env["run"]("--provider", "codex", http=http)
    r1 = datetime.fromisoformat(acc_of(s1, "codex")["fetch_error"]["retry_at"])
    assert r1 == T0 + timedelta(seconds=refresh.BACKOFF_BASE_SECONDS)

    env["clock"]["now"] = r1
    s2 = env["run"]("--provider", "codex", http=http)
    r2 = datetime.fromisoformat(acc_of(s2, "codex")["fetch_error"]["retry_at"])
    assert r2 - r1 == timedelta(seconds=refresh.BACKOFF_BASE_SECONDS * 2)
    assert http.calls["codex"] == 2


def test_one_request_per_credential_per_cycle(env, tmp_path):
    a = make_profile(tmp_path, "claude", "a", token="same")
    b = make_profile(tmp_path, "claude", "b", token="same")
    configure(env, tmp_path, {"claude": [a, b]})
    http = FakeHttp(claude=[http_error(429, "60")])
    status = env["run"](http=http)
    assert http.calls["claude"] == 1
    assert all(acc["fetch_error"]["kind"] == "rate_limited" for acc in status["agents"]["claude"]["accounts"])


def test_single_provider_refresh_keeps_other_providers_from_cache(env, tmp_path):
    configure(env, tmp_path, {
        "claude": [make_profile(tmp_path, "claude", "a")],
        "codex": [make_profile(tmp_path, "codex", "b")],
    })
    http = FakeHttp(claude=[API_OK["claude"]], codex=[API_OK["codex"]])
    first = env["run"](http=http)
    assert http.calls == {"claude": 1, "codex": 1, "gemini": 0}

    env["clock"]["now"] = T0 + timedelta(seconds=120)
    second = env["run"]("--provider", "claude", http=http)
    assert http.calls == {"claude": 2, "codex": 1, "gemini": 0}
    assert second["agents"]["codex"] == first["agents"]["codex"]
    assert acc_of(second, "claude")["fetched_at"] == env["clock"]["now"].isoformat()


def test_auth_error_reports_expired_login(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    status = env["run"](http=FakeHttp(claude=[http_error(401)]))
    acc = acc_of(status, "claude")
    assert acc["fetch_error"]["kind"] == "auth"
    assert acc["health"]["status"] == "session_expired"
    assert acc["no_data"] is True


def test_refresh_interval_minimum_is_enforced(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    status = env["run"]("--refresh-interval", "claude=5", http=FakeHttp(claude=[API_OK["claude"]]))
    assert acc_of(status, "claude")["next_check_at"] == (T0 + timedelta(seconds=refresh.MIN_INTERVAL_SECONDS)).isoformat()


def test_refresh_state_file_is_private_and_holds_no_secret(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a", token="sk-ant-SECRET")]})
    env["run"](http=FakeHttp(claude=[http_error(429, "60")]))
    state_file = env["cache"].with_name(refresh.STATE_FILENAME)
    assert stat.S_IMODE(os.stat(state_file).st_mode) == 0o600
    assert "SECRET" not in state_file.read_text()


def test_plasmoid_config_has_per_provider_interval_with_minimum():
    import xml.etree.ElementTree as ET
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "plasmoid" / "contents"
    entries = {e.attrib["name"]: e for e in ET.parse(root / "config" / "main.xml").getroot().iter() if e.tag.endswith("entry")}
    for name in ("Claude", "Codex", "Gemini"):
        entry = entries[f"refreshInterval{name}"]
        assert entry.find("{*}default").text == "3600"
        assert entry.find("{*}min").text == "3600"
    main_qml = (root / "ui" / "main.qml").read_text(encoding="utf-8")
    assert "--refresh-interval" in main_qml and "--provider" in main_qml
    # Revisao: remocao enfileirada durante execucao e watchdog de 120 s para isRefreshing preso
    assert "pendingRemovals.push" in main_qml and "interval: 120000" in main_qml
    model = (root / "ui" / "NotchModel.js").read_text(encoding="utf-8")
    assert "isNum(win.usage_percentage)" in model and "Stale data" in model


# --- Revisao do ticket 23 -------------------------------------------------------

def write_claude_history(profile, *moments):
    from pathlib import Path

    lines = [json.dumps({"timestamp": m.timestamp() * 1000}) for m in moments]
    (Path(profile["claude_dir"]) / "history.jsonl").write_text("\n".join(lines) + "\n")


def renew_claude_token(profile, token):
    future = (T0 + timedelta(days=5)).isoformat()
    with open(profile["credential_path"], "w", encoding="utf-8") as f:
        json.dump({"claudeAiOauth": {"accessToken": token, "expiresAt": future}}, f)


def test_window_without_own_history_has_no_percentage(env, tmp_path):
    """A1: historico so na janela semanal; a de 5h nao pode exibir 0% inventado."""
    from ai_usage_collector.contract import validate_status_contract

    prof = make_profile(tmp_path, "claude", "a")
    write_claude_history(prof, *(T0 - timedelta(days=2, seconds=i) for i in range(3)))
    configure(env, tmp_path, {"claude": [prof]})
    status = env["run"](http=FakeHttp(claude=[http_error(429, "226")]))

    acc = acc_of(status, "claude")
    nw, ww = acc["native_window"], acc["weekly_window"]
    assert nw["usage_percentage"] is None
    assert nw["used_capacity"] is None and nw["available_capacity"] is None
    assert nw["release_time"] is None
    assert ww["usage_percentage"] is None and ww["messages_used"] == 3
    assert acc["no_data"] is True
    assert validate_status_contract(status)


@pytest.mark.parametrize(
    "retry_after, expected_seconds",
    [
        ("inf", refresh.BACKOFF_BASE_SECONDS),
        ("nan", refresh.BACKOFF_BASE_SECONDS),
        ("-5", refresh.BACKOFF_BASE_SECONDS),
        ("abc", refresh.BACKOFF_BASE_SECONDS),
        ("1e20", refresh.MAX_PAUSE_SECONDS),
        ("99999999999", refresh.MAX_PAUSE_SECONDS),
        ("Tue, 20 Oct 2026 15:10:00 GMT", 600),
        ("Tue, 20 Oct 2026 15:10:00 -0000", 600),
    ],
)
def test_hostile_retry_after_is_bounded(env, tmp_path, retry_after, expected_seconds):
    """A2: retry-after infinito/gigante/invalido nunca derruba a coleta nem pausa para sempre."""
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    status = env["run"](http=FakeHttp(claude=[http_error(429, retry_after)]))
    retry_at = datetime.fromisoformat(acc_of(status, "claude")["fetch_error"]["retry_at"])
    assert retry_at == T0 + timedelta(seconds=expected_seconds)


def test_pause_survives_token_renewal(env, tmp_path):
    """M1: a pausa e da Conta, nao do token; o Claude Code renova o token com frequencia."""
    prof = make_profile(tmp_path, "claude", "a", token="tok-1")
    configure(env, tmp_path, {"claude": [prof]})
    http = FakeHttp(claude=[http_error(429, "226"), API_OK["claude"]])
    env["run"](http=http)

    renew_claude_token(prof, "tok-2")
    env["clock"]["now"] = T0 + timedelta(seconds=60)
    status = env["run"](http=http)
    assert http.calls["claude"] == 1
    assert acc_of(status, "claude")["fetch_error"]["kind"] == "rate_limited"


def test_cache_from_other_identity_is_not_served(env, tmp_path):
    """M2: o perfil passou a outro login; o cache da conta anterior nao pode aparecer."""
    prof = make_profile(tmp_path, "claude", "a", token="tok-1")
    configure(env, tmp_path, {"claude": [prof]})
    http = FakeHttp(claude=[{"five_hour": {"utilization": 88.0}, "seven_day": {"utilization": 77.0}}, http_error(429, "60")])
    env["run"](http=http)

    renew_claude_token(prof, "tok-OTHER")
    env["clock"]["now"] = T0 + timedelta(seconds=400)
    acc = acc_of(env["run"](http=http), "claude")
    assert acc["no_data"] is True
    assert acc["native_window"]["usage_percentage"] is None
    assert "fetched_at" not in acc


def test_cache_of_same_identity_survives_token_renewal(env, tmp_path):
    """M2: mesma Identidade da Conta (identity.py) com token renovado continua usando o cache."""
    prof = make_profile(tmp_path, "claude", "a", token="tok-1")
    from pathlib import Path
    (Path(prof["claude_dir"]) / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "uuid-a"}}))
    configure(env, tmp_path, {"claude": [prof]})
    http = FakeHttp(claude=[{"five_hour": {"utilization": 88.0}, "seven_day": {"utilization": 77.0}}, http_error(429, "60")])
    env["run"](http=http)

    renew_claude_token(prof, "tok-2")
    env["clock"]["now"] = T0 + timedelta(seconds=400)
    acc = acc_of(env["run"](http=http), "claude")
    assert acc["stale"] is True
    assert acc["native_window"]["usage_percentage"] == 88.0
    assert acc["fetched_at"] == T0.isoformat()


@pytest.mark.parametrize("provider, body", [
    ("claude", {"unexpected": True}),
    ("codex", {"unexpected": True}),
    ("gemini", {"unexpected": True}),
])
def test_200_without_expected_fields_is_invalid_response(env, tmp_path, provider, body):
    """M3: 200 sem os campos de uso nao e dado fresco."""
    configure(env, tmp_path, {provider: [make_profile(tmp_path, provider, "a")]})
    acc = acc_of(env["run"](http=FakeHttp(**{provider: [body]})), provider)
    assert acc["fetch_error"]["kind"] == "invalid_response"
    assert acc["stale"] is True
    assert acc["no_data"] is True
    assert "fetched_at" not in acc


@pytest.mark.parametrize("state", [
    "[]",
    "garbage",
    '{"credentials": {"x": "str"}}',
    '{"credentials": {"claude:a": {"paused_until": "abc"}}}',
    '{"credentials": {"claude:a": {"paused_until": "inf", "failures": "x"}}}',
    '{"credentials": []}',
])
def test_corrupt_refresh_state_is_ignored(env, tmp_path, state):
    """M4: estado invalido e descartado em vez de derrubar a coleta."""
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    env["cache"].parent.mkdir(parents=True, exist_ok=True)
    env["cache"].with_name(refresh.STATE_FILENAME).write_text(state)
    http = FakeHttp(claude=[API_OK["claude"]])
    status = env["run"](http=http)
    assert http.calls["claude"] == 1
    assert acc_of(status, "claude")["stale"] is False


def test_remove_account_waits_for_running_cycle(env, tmp_path):
    """M5: remocao usa o mesmo lock do ciclo de coleta."""
    import threading

    from ai_usage_collector.collector import remove_account

    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    env["run"](http=FakeHttp(claude=[API_OK["claude"]]))
    state_path = env["cache"].with_name(refresh.STATE_FILENAME)

    done = threading.Event()
    with refresh.status_lock(state_path):
        worker = threading.Thread(
            target=lambda: (remove_account("claude", "a", env["config"], env["cache"]), done.set())
        )
        worker.start()
        assert not done.wait(0.3)
    worker.join(5)
    assert done.is_set()
    assert json.loads(env["cache"].read_text())["agents"]["claude"]["accounts"] == []


@pytest.mark.parametrize("value", ["claude=abc", "foo=100", "claude", "=100"])
def test_invalid_refresh_interval_is_rejected_with_rc_2(env, tmp_path, value, capsys):
    """B1: valor ou provedor invalido gera mensagem amigavel e rc 2."""
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    rc = main(["--config-path", str(env["config"]), "--cache-path", str(env["cache"]),
               "--refresh", "--refresh-interval", value])
    assert rc == 2
    assert "intervalo" in capsys.readouterr().err.lower()
    assert not env["cache"].exists()


def test_refresh_interval_maximum_is_enforced(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    status = env["run"]("--refresh-interval", "claude=99999999999999", http=FakeHttp(claude=[API_OK["claude"]]))
    expected = T0 + timedelta(seconds=refresh.MAX_INTERVAL_SECONDS)
    assert acc_of(status, "claude")["next_check_at"] == expected.isoformat()


def test_no_data_after_429_keeps_api_baseline_and_never_notes():
    from ai_usage_collector.limit_changes import apply_limit_changes

    def win(**kw):
        return {"usage_percentage": 40.0, "messages_used": 0, "window_seconds": 18000,
                "release_time": (T0 + timedelta(hours=2)).isoformat(), "source": "api",
                "api_fields": ["duration", "release"], **kw}

    # cache antigo (sem fetched_at): leitura valida da API
    previous = {"id": "a", "health": {"status": "valid"}, "native_window": win(), "weekly_window": win()}
    entry = {"id": "a", "health": {"status": "valid"},
             "native_window": win(source="local", api_fields=[], window_seconds=10800),
             "weekly_window": win(source="local", api_fields=[], window_seconds=10800)}
    outcome = {"kind": "rate_limited", "retry_at": T0.timestamp() + 60, "credential": "claude:x"}
    refresh.apply_outcome(entry, outcome, previous, T0, 300)

    assert entry["no_data"] is True
    nw = entry["native_window"]
    assert (nw["source"], nw["api_fields"], nw["window_seconds"]) == ("api", ["duration", "release"], 18000)
    assert nw["usage_percentage"] is None and nw["release_time"] is None

    status = {"agents": {"claude": {"accounts": [entry]}}}
    apply_limit_changes(status, {"agents": {"claude": {"accounts": [previous]}}}, T0)
    assert "limit_changes" not in entry


def _req():
    return urllib.request.Request("https://api.anthropic.com/x")


@pytest.mark.parametrize("exc", [http.client.IncompleteRead(b"x"), http.client.BadStatusLine("x")])
def test_http_client_errors_degrade_to_network(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(refresh.FetchError) as e:
        refresh.request_json(_req(), 1)
    assert e.value.kind == "network"


@pytest.mark.parametrize("hostile", [1e18, 1e300, "99999999999999"])
def test_hostile_paused_until_is_clamped(tmp_path, hostile):
    path = tmp_path / "refresh_state.json"
    path.write_text(json.dumps({"credentials": {"claude:a": {"paused_until": hostile, "failures": 10**6}}}))
    cyc = refresh.RefreshCycle(path, T0)
    entry = cyc.state["claude:a"]
    assert entry["paused_until"] <= T0.timestamp() + refresh.MAX_PAUSE_SECONDS
    assert entry["failures"] <= refresh.MAX_FAILURES
    cyc.save()  # nao quebra
    assert refresh._iso(1e300)  # nao levanta


def test_pause_is_saved_even_if_cycle_raises(tmp_path):
    path = tmp_path / "refresh_state.json"
    with pytest.raises(RuntimeError):
        with refresh.cycle(path, T0) as cyc:
            cyc.state["claude:a"] = {"paused_until": T0.timestamp() + 60, "failures": 1}
            raise RuntimeError("coleta falhou")
    assert "claude:a" in json.loads(path.read_text())["credentials"]
    assert (path.with_suffix(".lock").stat().st_mode & 0o777) == 0o600


def test_idle_account_with_null_windows_is_a_valid_response(env, tmp_path):
    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    status = env["run"]("--provider", "claude", http=FakeHttp(claude=[{"five_hour": None, "seven_day": None}]))
    acc = acc_of(status, "claude")
    assert acc["stale"] is False and acc["no_data"] is True and "fetch_error" not in acc


def test_remove_account_forgets_its_pause(env, tmp_path):
    from ai_usage_collector.collector import remove_account

    configure(env, tmp_path, {"claude": [make_profile(tmp_path, "claude", "a")]})
    env["run"]("--provider", "claude", http=FakeHttp(claude=[http_error(429, "226")]))
    state_path = env["cache"].with_name(refresh.STATE_FILENAME)
    assert "claude:a" in json.loads(state_path.read_text())["credentials"]
    ok, _ = remove_account("claude", "a", env["config"], env["cache"])
    assert ok and "claude:a" not in json.loads(state_path.read_text())["credentials"]


def test_stale_card_hides_percentage_after_release_passed():
    qml = (Path(__file__).parent.parent / "plasmoid/contents/ui/NotchModel.js").read_text()  # o popup usa windowView -> windowPct
    assert 'acc.stale === true && !isNaN(reset) && reset <= Date.now()' in qml
    assert 'windowPct(acc, win, key)' in qml and 'cycle_reset_time' in qml and 'release_time' in qml


def test_claude_validator_rejects_non_dict_window():
    # regressao: {"seven_day": "x"} passava no validador e quebrava o extrator com AttributeError
    from ai_usage_collector.extractors import claude
    from ai_usage_collector import refresh

    captured = {}

    def fake_fetch(provider, token, req, timeout, opener=None, valid=None):
        captured["valid"] = valid

    orig = refresh.fetch_json
    refresh.fetch_json = fake_fetch
    try:
        claude.fetch_claude_usage_api("tok")
    finally:
        refresh.fetch_json = orig
    valid = captured["valid"]
    assert valid({"five_hour": None, "seven_day": None})
    assert valid({"five_hour": {"utilization": 1}})
    assert not valid({"five_hour": None, "seven_day": "x"})
    assert not valid({"seven_day": [1]})
    assert not valid({})


def test_gemini_expired_token_makes_no_quota_call_and_shows_no_data(env, tmp_path):
    prof = make_profile(tmp_path, "gemini", "a")
    creds = Path(prof["credential_path"])
    creds.write_text(json.dumps({
        "access_token": "tok-vencido", "refresh_token": "r",
        "expiry_date": int((T0 - timedelta(hours=40)).timestamp() * 1000),
    }))
    (Path(prof["gemini_dir"]) / "history.jsonl").write_text(
        json.dumps({"timestamp": int(T0.timestamp() * 1000) - 60000, "display": "oi"}) + "\n"
    )
    configure(env, tmp_path, {"gemini": [prof]})
    http = FakeHttp(gemini=[API_OK["gemini"]])

    status = env["run"]("--provider", "gemini", http=http)

    acc = acc_of(status, "gemini")
    assert http.calls["gemini"] == 0
    assert acc["no_data"] is True
    for win in ("native_window", "weekly_window"):
        assert acc[win]["usage_percentage"] is None
    assert acc["native_window"]["messages_used"] == 1  # historico local segue como informacao auxiliar
    assert "tok-vencido" not in json.dumps(status)


def test_gemini_network_failure_keeps_last_data_stale(env, tmp_path):
    configure(env, tmp_path, {"gemini": [make_profile(tmp_path, "gemini", "a")]})
    http = FakeHttp(gemini=[API_OK["gemini"], urllib.error.URLError("sem rede")])
    env["run"]("--provider", "gemini", "--refresh-interval", "gemini=3600", http=http)

    env["clock"]["now"] = T0 + timedelta(seconds=3600)
    status = env["run"]("--provider", "gemini", http=http)

    acc = acc_of(status, "gemini")
    assert acc["stale"] is True
    assert acc["fetch_error"]["kind"] == "network"
    assert acc["fetched_at"] == T0.isoformat()
    assert acc["native_window"]["usage_percentage"] == 42.0
    assert "no_data" not in acc


GEMINI_SUMMARY = {"groups": [{"displayName": "Claude and GPT models", "buckets": [
    {"bucketId": "3p-5h", "window": "5h", "remainingFraction": 1, "resetTime": "2026-10-20T20:00:00Z"}]}]}
GEMINI_MODELS = {"buckets": [
    {"modelId": "gemini-2.5-pro", "remainingFraction": 0.83, "resetTime": "2026-10-20T18:00:00Z"}]}


def test_gemini_one_call_per_endpoint_per_query_and_models_reach_highlight(env, tmp_path):
    configure(env, tmp_path, {"gemini": [make_profile(tmp_path, "gemini", "a")]})
    http = FakeHttp(gemini=[GEMINI_SUMMARY], gemini_models=[GEMINI_MODELS])

    status = env["run"]("--provider", "gemini", http=http)

    assert sorted(u.rsplit(":", 1)[1] for u in http.urls) == ["retrieveUserQuota", "retrieveUserQuotaSummary"]
    acc = acc_of(status, "gemini")
    assert acc["native_window"]["usage_percentage"] == 17.0
    assert acc["stale"] is False


def test_gemini_429_on_first_endpoint_pauses_account_and_skips_second_call(env, tmp_path):
    configure(env, tmp_path, {"gemini": [make_profile(tmp_path, "gemini", "a")]})
    http = FakeHttp(gemini=[http_error(429, "226")], gemini_models=[GEMINI_MODELS])

    status = env["run"]("--provider", "gemini", http=http)

    assert http.calls["gemini"] == 1
    acc = acc_of(status, "gemini")
    assert acc["fetch_error"]["kind"] == "rate_limited" and acc["no_data"] is True


def test_gemini_429_on_second_endpoint_pauses_account(env, tmp_path):
    configure(env, tmp_path, {"gemini": [make_profile(tmp_path, "gemini", "a")]})
    http = FakeHttp(gemini=[GEMINI_SUMMARY], gemini_models=[http_error(429, "226")])

    status = env["run"]("--provider", "gemini", http=http)
    acc = acc_of(status, "gemini")
    assert acc["fetch_error"]["kind"] == "rate_limited"

    env["clock"]["now"] = T0 + timedelta(seconds=60)
    env["run"]("--provider", "gemini", http=http)
    assert http.calls["gemini"] == 2  # pausada: nenhuma chamada nova


def test_gemini_one_endpoint_failing_keeps_the_other_fresh(env, tmp_path):
    configure(env, tmp_path, {"gemini": [make_profile(tmp_path, "gemini", "a")]})
    summary = {"groups": [{"displayName": "Gemini Models", "buckets": [
        {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 1,
         "resetTime": "2026-10-20T20:00:00Z"}]}]}
    http = FakeHttp(gemini=[summary], gemini_models=[urllib.error.URLError("sem rede")])

    status = env["run"]("--provider", "gemini", http=http)

    acc = acc_of(status, "gemini")
    assert acc["stale"] is False and "fetch_error" not in acc
    assert acc["native_window"]["usage_percentage"] == 0.0
