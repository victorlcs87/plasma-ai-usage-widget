"""Atualizacao periodica por provedor (ADR-0007): 429/retry-after, backoff, cache desatualizado."""

import json
import os
import stat
import urllib.error
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

    def read(self):
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

    def __call__(self, req, timeout=None):
        prov = next(p for p, host in PROVIDER_URLS.items() if host in req.full_url)
        queue = self.responses[prov]
        resp = queue[min(self.calls[prov], len(queue) - 1)]
        self.calls[prov] += 1
        if isinstance(resp, Exception):
            raise resp
        return FakeResp(resp)


def make_profile(tmp_path, provider, name, token="tok-1"):
    """Perfil isolado sem historico local, com credencial valida."""
    d = tmp_path / "profiles" / provider / name
    d.mkdir(parents=True)
    future = (T0 + timedelta(days=5))
    if provider == "claude":
        cred = d / ".credentials.json"
        cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": future.isoformat()}}))
        return {"id": name, "label": name, "claude_dir": str(d), "credential_path": str(cred)}
    if provider == "codex":
        cred = d / "auth.json"
        cred.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": token, "account_id": "acc"}}))
        return {"id": name, "label": name, "codex_dir": str(d), "credential_path": str(cred)}
    cred = d / "oauth_creds.json"
    cred.write_text(json.dumps({"access_token": token, "refresh_token": "r", "expiry_date": int(future.timestamp() * 1000)}))
    return {"id": name, "label": name, "gemini_dir": str(d), "credential_path": str(cred)}


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = {"now": T0}
    monkeypatch.setattr(refresh, "utcnow", lambda: clock["now"])
    paths = {"config": tmp_path / "config.json", "cache": tmp_path / "cache" / "status.json", "clock": clock}

    def run(*args, http):
        monkeypatch.setattr("urllib.request.urlopen", http)
        rc = main(["--config-path", str(paths["config"]), "--cache-path", str(paths["cache"]), "--refresh", *args])
        assert rc == 0
        return json.loads(paths["cache"].read_text())

    paths["run"] = run
    return paths


def configure(env, tmp_path, accounts_by_provider):
    save_config({"version": 1, "agents": {p: {"accounts": accs} for p, accs in accounts_by_provider.items()}}, env["config"])


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
    first = env["run"]("--provider", "claude", "--refresh-interval", "claude=300", http=http)
    acc = acc_of(first, "claude")
    assert acc["stale"] is False
    assert acc["fetched_at"] == T0.isoformat()
    assert acc["next_check_at"] == (T0 + timedelta(seconds=300)).isoformat()
    assert first["agents"]["claude"]["fetched_at"] == T0.isoformat()

    env["clock"]["now"] = T0 + timedelta(seconds=300)
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
        assert entry.find("{*}default").text == "300"
        assert entry.find("{*}min").text == "60"
    main_qml = (root / "ui" / "main.qml").read_text(encoding="utf-8")
    assert "--refresh-interval" in main_qml and "--provider" in main_qml
