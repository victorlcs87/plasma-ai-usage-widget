"""Mensagem de login vencido por estado da Conta no popup (Spec 08, ticket 61), em qml6 offscreen."""
import pytest

from test_plasmoid_popup import acct, fixture, popup, pytestmark  # noqa: F401

CASES = [
    (None, "token expired; automatic renewal will be retried"),
    ({"error": None, "at": "2026-10-20T15:00:00+00:00"}, "renewal ran, but the provider still refuses the token"),
    ({"error": "revoked"}, "login revoked at the provider"),
    ({"error": "cli_missing"}, "automatic renewal failed (the provider CLI was not found)"),
    ({"error": "binary_missing"}, "automatic renewal failed (the Antigravity binary was not found)"),
    ({"error": "timeout"}, "automatic renewal failed (timed out)"),
    ({"error": "network"}, "automatic renewal failed (network error)"),
    ({"error": "disabled"}, "Automatic renewal is off for Gemini accounts"),
    ({"error": "failed"}, "automatic renewal failed. Log in"),
    ({"error": "no_valid_secret"}, "automatic renewal failed. Log in"),  # codigo interno novo cai no generico
]


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini"])
@pytest.mark.parametrize("renewal,expect", CASES)
def test_expired_login_message_names_the_account_state_and_how_to_reactivate(tmp_path, provider, renewal, expect):
    data = fixture()
    acc = acct(provider, "x", "Conta Teste", False, health="session_expired", no_data=True, stale=True,
               fetch_error={"kind": "auth", "message": "Login expirado", "retry_at": None})
    if renewal is not None:
        acc["renewal"] = renewal
    data["agents"][provider]["accounts"] = [acc]
    drive = ("obs('lines', all(f).filter(function (k) { return k.visible && typeof k.text === 'string' && k.text.indexOf('\\u26a0') === 0 })"
             ".map(function (k) { return k.text }))")
    out = popup(tmp_path, "auth_" + provider, data=data, drive=drive, size=(460, 700))
    assert len(out["lines"]) == 1
    line = out["lines"][0]
    assert line.startswith("⚠ Conta Teste: ") and expect in line
    assert "Log in at the provider with this account" in line or "log in at the provider with this account" in line
    assert "Activate on System" not in line  # o botão fica oculto com a sessão expirada


@pytest.mark.parametrize("active,expect", [(True, "automatic renewal failed. Log in"), (False, "automatic renewal failed. Log in")])
def test_active_account_gets_no_renewal_promise_and_hostile_error_stays_inert(tmp_path, active, expect):
    data = fixture()
    acc = acct("claude", "x", "Conta <b>x</b>", active, health="session_expired", no_data=True,
               fetch_error={"kind": "auth", "message": "m", "retry_at": None}, renewal={"error": "<b>x</b>", "at": "t"})
    data["agents"]["claude"]["accounts"] = [acc]
    drive = ("obs('lines', all(f).filter(function (k) { return k.visible && typeof k.text === 'string' && k.text.indexOf('\\u26a0') === 0 })"
             ".map(function (k) { return [k.text, k.textFormat === Text.PlainText] }))")
    out = popup(tmp_path, "auth_active", data=data, drive=drive, size=(460, 700))
    (text, plain), = out["lines"]
    assert plain and expect in text and "<b>x</b>: " in text
    assert ("will be retried" not in text) if active else True


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini"])
def test_expired_account_button_requests_scoped_renewal(tmp_path, provider):
    data = fixture()
    for agent in data["agents"].values():
        agent["accounts"] = []
    data["agents"][provider]["accounts"] = [acct(provider, "target", "Expired account", False,
        health="session_expired", no_data=True, fetch_error={"kind": "auth"})]
    out = popup(tmp_path, "manual_renew_" + provider, data=data, size=(600,700), drive="""
        obs('renewButtons', vis('renewSessionButton').length)
        btn('Renew session').click()
        obs('commands', Log.cmds)
    """)
    assert out["renewButtons"] == 1
    assert len(out["commands"]) == 1
    assert "'--renew-account' '" + provider + "' 'target' '--status'" in out["commands"][0]


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini"])
def test_successful_renewal_displays_fresh_usage_without_reopening(tmp_path, provider):
    data = fixture()
    for agent in data["agents"].values():
        agent["accounts"] = []
    data["agents"][provider]["accounts"] = [acct(provider, "target", "Expired account", False,
        health="session_expired", no_data=True, fetch_error={"kind": "auth"})]
    drive = """
        btn('Renew session').click()
        var fresh = JSON.parse(JSON.stringify(logic.statusData))
        var account = fresh.agents.PROVIDER.accounts[0]
        account.health.status = 'valid'
        account.native_window = {usage_percentage: 37, window_seconds: 18000, release_time: '2099-01-01T00:00:00Z'}
        delete account.fetch_error
        delete account.no_data
        delete account.stale
        for (var i = 0; i < Log.sources.length; i++) Log.sources[i].newData(Log.cmds[0], {'exit code': 0, stdout: JSON.stringify(fresh)})
        wait(50)
        obs('percentages', txt('pct'))
        obs('remainingButtons', vis('renewSessionButton').length)
        obs('refreshing', logic.isRefreshing)
    """.replace('PROVIDER', provider)
    out = popup(tmp_path, "renew_success_" + provider, data=data, drive=drive, size=(600,700))
    assert "37%" in out["percentages"]
    assert out["remainingButtons"] == 0
    assert out["refreshing"] is False


@pytest.mark.parametrize("error_code,expect", [
    ("cli_running", "close the provider CLI, then click Renew session to refresh this account safely."),
    ("detection_failed", "could not safely identify the active session. Close the provider CLI and try Renew session again."),
])
def test_manual_renewal_failure_displays_guidance_feedback(tmp_path, error_code, expect):
    data = fixture()
    for agent in data["agents"].values():
        agent["accounts"] = []
    data["agents"]["claude"]["accounts"] = [acct("claude", "target", "Active account", True,
        health="session_expired", no_data=True, fetch_error={"kind": "auth"})]
    drive = """
        btn('Renew session').click()
        var fresh = JSON.parse(JSON.stringify(logic.statusData))
        var account = fresh.agents.claude.accounts[0]
        account.renewal = {error: 'ERROR_CODE', at: '2026-10-24T18:00:00Z'}
        for (var i = 0; i < Log.sources.length; i++) Log.sources[i].newData(Log.cmds[0], {'exit code': 0, stdout: JSON.stringify(fresh)})
        wait(50)
        obs('texts', all(f).filter(function (k) { return k.visible && typeof k.text === 'string' }).map(function (k) { return k.text }))
        obs('refreshing', logic.isRefreshing)
    """.replace('ERROR_CODE', error_code)
    out = popup(tmp_path, "renew_feedback_" + error_code, data=data, drive=drive, size=(600, 700))
    joined = " ".join(out["texts"])
    assert expect in joined
    assert out["refreshing"] is False


def test_manual_renewal_with_http_429_displays_pause_and_hides_button(tmp_path):
    data = fixture()
    for agent in data["agents"].values():
        agent["accounts"] = []
    data["agents"]["claude"]["accounts"] = [acct("claude", "target", "Active account", True,
        health="session_expired", no_data=True, fetch_error={"kind": "auth"})]
    drive = """
        btn('Renew session').click()
        var fresh = JSON.parse(JSON.stringify(logic.statusData))
        var account = fresh.agents.claude.accounts[0]
        account.health.status = 'valid'
        account.renewal = {error: null, at: '2026-10-24T18:00:00Z'}
        account.fetch_error = {kind: 'rate_limited', message: 'Rate limit (HTTP 429)'}
        account.stale = true
        for (var i = 0; i < Log.sources.length; i++) Log.sources[i].newData(Log.cmds[0], {'exit code': 0, stdout: JSON.stringify(fresh)})
        wait(50)
        obs('remainingButtons', vis('renewSessionButton').length)
        obs('statusLines', all(f).filter(function (k) { return k.visible && typeof k.text === 'string' && k.text.indexOf('\\u26a0') === 0 }).map(function (k) { return k.text }))
        obs('refreshing', logic.isRefreshing)
    """
    out = popup(tmp_path, "renew_rate_limit", data=data, drive=drive, size=(600, 700))
    assert out["remainingButtons"] == 0
    joined = " ".join(out["statusLines"])
    assert "Provider rate limit reached (HTTP 429)" in joined or "HTTP 429" in joined
    assert out["refreshing"] is False
