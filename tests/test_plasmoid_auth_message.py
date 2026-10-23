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


@pytest.mark.parametrize("active,expect", [(True, "login expired at the provider"), (False, "automatic renewal failed. Log in")])
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
