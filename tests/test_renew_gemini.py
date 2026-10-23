"""Renovacao da Conta Gemini inativa com refresh_token (Spec 08, ticket 60). HTTP e binario falsos."""

import base64
import json
import os
import stat
import urllib.error
import urllib.parse
from datetime import timedelta
from io import BytesIO

import pytest

from ai_usage_collector import renew
from test_refresh import API_OK, T0, FakeHttp, FakeResp, acc_of, configure, env, make_profile  # noqa: F401

REAL_RENEWERS = dict(renew.RENEWERS)
CLIENT_ID = "1071006060591-fakeclient123.apps.googleusercontent.com"
GOOD = "GOCSPX-" + "G" * 28
BAD = "GOCSPX-" + "B" * 28
OLD_ACCESS, OLD_REFRESH, NEW_ACCESS = "ya29.ANTIGO", "1//REFRESH-ANTIGO", "ya29.NOVO"


def _id_token(aud=CLIENT_ID):
    seg = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{seg({'alg': 'none'})}.{seg({'aud': aud})}.sig"


def _profile(tmp_path, name="g", aud=CLIENT_ID):
    prof = make_profile(tmp_path, "gemini", name)
    creds = {
        "access_token": OLD_ACCESS, "refresh_token": OLD_REFRESH, "id_token": _id_token(aud),
        "token_type": "Bearer", "auth_method": "consumer", "expires_in": 3599,
        "expiry": (T0 - timedelta(hours=40)).isoformat(),
    }
    open(prof["credential_path"], "w").write(json.dumps(creds))
    return prof


def _creds(prof):
    return json.loads(open(prof["credential_path"]).read())


class TokenHttp(FakeHttp):
    """Endpoint de token falso: responde por segredo recebido; o resto vai para o FakeHttp."""

    def __init__(self, token_replies, **kw):
        super().__init__(**kw)
        self.token_replies = token_replies  # {segredo: dict | Exception}
        self.token_calls = []

    def __call__(self, req, timeout=None):
        if "oauth2.googleapis.com" not in req.full_url:
            return super().__call__(req, timeout)
        form = urllib.parse.parse_qs(req.data.decode())
        assert form["grant_type"] == ["refresh_token"] and form["client_id"] == [CLIENT_ID]
        self.token_calls.append(form["client_secret"][0])
        reply = self.token_replies[form["client_secret"][0]]
        if isinstance(reply, Exception):
            raise reply
        return FakeResp(reply)


def oauth_error(code, error):
    return urllib.error.HTTPError(renew.GOOGLE_TOKEN_URL, code, "x", {}, BytesIO(json.dumps({"error": error}).encode()))


OK = {"access_token": NEW_ACCESS, "expires_in": 3599, "token_type": "Bearer", "scope": "x"}


@pytest.fixture
def agy(tmp_path, monkeypatch):
    monkeypatch.setattr(renew, "RENEWERS", REAL_RENEWERS)
    path = tmp_path / "agy"

    def install(content=None):
        data = b"\x00junk" + CLIENT_ID.encode() + b"\x00" * 50 + BAD.encode() + b"\x00" * 50 + GOOD.encode() + b"lixo"
        path.write_bytes(data if content is None else content)

    install()
    monkeypatch.setattr(renew, "_agy_binary", lambda: path)
    return type("A", (), {"install": staticmethod(install), "path": path})


def _run(env, http):
    return env["run"]("--provider", "gemini", http=http)


def _state(env):
    return json.loads((env["cache"].parent / "refresh_state.json").read_text())["renewals"]


def _no_leak(env, *secrets):
    blob = env["cache"].read_text() + (env["cache"].parent / "refresh_state.json").read_text()
    for s in secrets:
        assert s not in blob


def test_wrong_candidate_first_then_right_one_renews_and_keeps_refresh_token(env, tmp_path, agy, capsys):
    prof = _profile(tmp_path)
    configure(env, tmp_path, {"gemini": [prof]})
    http = TokenHttp({BAD: oauth_error(401, "invalid_client"), GOOD: OK}, gemini=[API_OK["gemini"]])

    status = _run(env, http)

    assert http.token_calls == [BAD, GOOD]
    c = _creds(prof)
    assert (c["access_token"], c["refresh_token"], c["expires_in"]) == (NEW_ACCESS, OLD_REFRESH, 3599)
    assert c["expiry"] == (T0 + timedelta(seconds=3599)).isoformat() and c["auth_method"] == "consumer"
    assert stat.S_IMODE(os.stat(prof["credential_path"]).st_mode) == 0o600
    assert "fetch_error" not in acc_of(status, "gemini")
    assert _state(env)["gemini:g"]["error"] is None
    _no_leak(env, GOOD, BAD, NEW_ACCESS, OLD_REFRESH)
    err = capsys.readouterr()
    assert GOOD not in err.err + err.out and BAD not in err.err + err.out


def test_rotated_refresh_and_id_token_are_stored(env, tmp_path, agy):
    prof = _profile(tmp_path)
    configure(env, tmp_path, {"gemini": [prof]})
    new_id = _id_token()
    _run(env, TokenHttp({BAD: OK | {"refresh_token": "1//NOVO", "id_token": new_id}, GOOD: OK}, gemini=[API_OK["gemini"]]))
    c = _creds(prof)
    assert (c["refresh_token"], c["id_token"]) == ("1//NOVO", new_id)


def test_no_valid_candidate(env, tmp_path, agy):
    prof = _profile(tmp_path)
    configure(env, tmp_path, {"gemini": [prof]})
    http = TokenHttp({BAD: oauth_error(401, "invalid_client"), GOOD: oauth_error(401, "invalid_client")},
                     gemini=[API_OK["gemini"]])
    status = _run(env, http)
    assert _state(env)["gemini:g"]["error"] == "no_valid_secret"
    assert _creds(prof)["access_token"] == OLD_ACCESS
    assert len(status["agents"]["gemini"]["accounts"]) == 1
    _no_leak(env, GOOD, BAD)


def test_missing_binary(env, tmp_path, monkeypatch, agy):
    def boom():
        raise renew.RenewError("binary_missing")

    monkeypatch.setattr(renew, "_agy_binary", boom)
    configure(env, tmp_path, {"gemini": [_profile(tmp_path)]})
    http = TokenHttp({}, gemini=[API_OK["gemini"]])
    _run(env, http)
    assert _state(env)["gemini:g"]["error"] == "binary_missing" and http.token_calls == []


def test_agy_binary_lookup_missing_is_classified(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(renew.RenewError) as exc:
        renew._agy_binary()  # HOME isolado: ~/.local/bin/agy nao existe
    assert exc.value.code == "binary_missing"


def test_client_id_absent_from_binary_tries_nothing(env, tmp_path, agy):
    agy.install(b"nada " + GOOD.encode())
    configure(env, tmp_path, {"gemini": [_profile(tmp_path)]})
    http = TokenHttp({GOOD: OK}, gemini=[API_OK["gemini"]])
    _run(env, http)
    assert _state(env)["gemini:g"]["error"] == "client_id_not_in_binary" and http.token_calls == []


def test_invalid_aud_is_classified(env, tmp_path, agy):
    configure(env, tmp_path, {"gemini": [_profile(tmp_path, aud="evil.example.com")]})
    http = TokenHttp({GOOD: OK}, gemini=[API_OK["gemini"]])
    _run(env, http)
    assert _state(env)["gemini:g"]["error"] == "client_id_missing" and http.token_calls == []


def test_candidates_are_capped_and_deduplicated(tmp_path, agy):
    many = b"".join(b"GOCSPX-" + str(i).zfill(28).encode() + b" " for i in range(20))
    agy.install(CLIENT_ID.encode() + b" " + (GOOD.encode() + b" ") * 3 + many)
    found = renew._secret_candidates(agy.path, CLIENT_ID)
    assert len(found) == renew.MAX_SECRET_CANDIDATES and found[0] == GOOD and len(set(found)) == len(found)


def test_invalid_grant_is_revoked_and_stops(env, tmp_path, agy):
    prof = _profile(tmp_path)
    configure(env, tmp_path, {"gemini": [prof]})
    http = TokenHttp({BAD: oauth_error(400, "invalid_grant"), GOOD: OK}, gemini=[API_OK["gemini"]])
    _run(env, http)
    assert http.token_calls == [BAD] and _state(env)["gemini:g"]["error"] == "revoked"
    assert _creds(prof)["access_token"] == OLD_ACCESS


def test_network_error_stops(env, tmp_path, agy):
    configure(env, tmp_path, {"gemini": [_profile(tmp_path)]})
    http = TokenHttp({BAD: urllib.error.URLError("sem rede"), GOOD: OK}, gemini=[API_OK["gemini"]])
    _run(env, http)
    assert http.token_calls == [BAD] and _state(env)["gemini:g"]["error"] == "network"


def test_invalid_response_does_not_corrupt_file(env, tmp_path, agy):
    prof = _profile(tmp_path)
    before = open(prof["credential_path"]).read()
    configure(env, tmp_path, {"gemini": [prof]})
    _run(env, TokenHttp({BAD: {"access_token": ""}, GOOD: OK}, gemini=[API_OK["gemini"]]))
    assert _state(env)["gemini:g"]["error"] == "invalid_response"
    assert open(prof["credential_path"]).read() == before


def test_failure_in_one_account_does_not_affect_other(env, tmp_path, agy):
    a, b = _profile(tmp_path, "a", aud="evil.example.com"), _profile(tmp_path, "b")
    configure(env, tmp_path, {"gemini": [a, b]})
    status = _run(env, TokenHttp({BAD: OK, GOOD: OK}, gemini=[API_OK["gemini"]]))
    st = _state(env)
    assert st["gemini:a"]["error"] == "client_id_missing" and st["gemini:b"]["error"] is None
    assert _creds(b)["access_token"] == NEW_ACCESS and len(status["agents"]["gemini"]["accounts"]) == 2


def test_active_system_account_is_never_renewed_nor_written(env, tmp_path, agy, monkeypatch):
    prof = _profile(tmp_path, "ativa")
    sys_dir = tmp_path / "_sys_gemini"
    sys_dir.mkdir()
    (sys_dir / "oauth_creds.json").write_text(open(prof["credential_path"]).read())
    monkeypatch.setenv("GEMINI_CONFIG_DIR", str(sys_dir))
    configure(env, tmp_path, {"gemini": [prof]})
    before = (sys_dir / "oauth_creds.json").read_text()
    http = TokenHttp({BAD: OK, GOOD: OK}, gemini=[API_OK["gemini"]])
    _run(env, http)
    assert http.token_calls == [] and (sys_dir / "oauth_creds.json").read_text() == before


def test_stale_expiry_date_is_dropped_so_new_token_is_not_seen_as_expired(env, tmp_path, agy):
    prof = _profile(tmp_path)
    c = _creds(prof)
    c["expiry_date"] = 1000
    open(prof["credential_path"], "w").write(json.dumps(c))
    configure(env, tmp_path, {"gemini": [prof]})
    _run(env, TokenHttp({BAD: OK, GOOD: OK}, gemini=[API_OK["gemini"]]))
    assert "expiry_date" not in _creds(prof)


def test_symlinked_credential_is_not_written_through(env, tmp_path, agy):
    prof = _profile(tmp_path)
    real = tmp_path / "fora.json"
    real.write_text(open(prof["credential_path"]).read())
    link = tmp_path / "profiles/gemini/g/oauth_creds.json"
    link.unlink()
    link.symlink_to(real)
    configure(env, tmp_path, {"gemini": [prof]})
    before = real.read_text()
    _run(env, TokenHttp({BAD: OK, GOOD: OK}, gemini=[API_OK["gemini"]]))
    assert real.read_text() == before
    assert not list(link.parent.glob(".oauth_*"))
