import base64
import json
from unittest.mock import patch

from ai_usage_collector.discovery import (
    discover_claude,
    discover_codex,
    discover_gemini,
    extract_jwt_identity,
    discover_account,
)


def make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


def test_extract_jwt_identity():
    token = make_jwt({"email": "dev@example.com", "name": "Developer"})
    assert extract_jwt_identity(token) == "dev@example.com"

    token_sub = make_jwt({"sub": "user-12345"})
    assert extract_jwt_identity(token_sub) == "user-12345"

    assert extract_jwt_identity("invalid.token") is None
    assert extract_jwt_identity(None) is None


def test_discover_claude_missing_file(tmp_path):
    cred_file = tmp_path / "missing.json"
    health = discover_claude(cred_file)
    assert health["status"] == "missing_credentials"
    assert health["detected"] is False


def test_discover_claude_invalid_json(tmp_path):
    cred_file = tmp_path / "corrupted.json"
    cred_file.write_text("invalid json contents")
    health = discover_claude(cred_file)
    assert health["status"] == "auth_error"
    assert health["detected"] is True


def test_discover_claude_valid_credentials(tmp_path):
    cred_file = tmp_path / "claude_creds.json"
    cred_data = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-test-token",
            "subscriptionType": "pro",
            "rateLimitTier": "tier_1",
            "expiresAt": "2099-01-01T00:00:00Z",
        }
    }
    cred_file.write_text(json.dumps(cred_data))
    health = discover_claude(cred_file)
    assert health["status"] == "valid"
    assert health["detected"] is True
    assert health["metadata"]["subscription_type"] == "pro"


def test_discover_claude_expired_session(tmp_path):
    cred_file = tmp_path / "claude_creds_expired.json"
    cred_data = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-test-token",
            "subscriptionType": "pro",
            "rateLimitTier": "tier_1",
            "expiresAt": "2020-01-01T00:00:00Z",
        }
    }
    cred_file.write_text(json.dumps(cred_data))
    health = discover_claude(cred_file)
    assert health["status"] == "session_expired"
    assert health["detected"] is True
    assert "expirada" in health["message"].lower()


def test_discover_codex_valid_tokens(tmp_path):
    cred_file = tmp_path / "codex_auth.json"
    id_tok = make_jwt({"email": "codex-user@company.com"})
    cred_data = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "token-123",
            "id_token": id_tok,
            "account_id": "acc-987",
        },
        "last_refresh": "2026-10-20T08:00:00Z",
    }
    cred_file.write_text(json.dumps(cred_data))
    health = discover_codex(cred_file)
    assert health["status"] == "valid"
    assert health["detected"] is True
    assert health["metadata"]["email"] == "codex-user@company.com"
    assert health["metadata"]["account_id"] == "acc-987"


def test_discover_gemini_valid_tokens(tmp_path):
    cred_file = tmp_path / "gemini_creds.json"
    id_tok = make_jwt({"email": "gemini-user@gmail.com"})
    cred_data = {
        "access_token": "ya29.test",
        "refresh_token": "1//refresh",
        "id_token": id_tok,
        "expiry_date": 1800000000,
        "token_type": "Bearer",
    }
    cred_file.write_text(json.dumps(cred_data))
    health = discover_gemini(cred_file)
    assert health["status"] == "valid"
    assert health["detected"] is True
    assert health["metadata"]["email"] == "gemini-user@gmail.com"


def test_discover_account_dispatcher(tmp_path):
    cred_file = tmp_path / "creds.json"
    cred_file.write_text(json.dumps({"access_token": "test"}))

    h_claude = discover_account("claude", cred_file)
    assert h_claude["detected"] is True

    h_codex = discover_account("codex", cred_file)
    assert h_codex["detected"] is True

    h_gemini = discover_account("gemini", cred_file)
    assert h_gemini["status"] == "valid"


def test_discover_gemini_expired_file_overridden_by_keyring(tmp_path):
    cred_file = tmp_path / "gemini_expired.json"
    expired_data = {
        "access_token": "ya29.expired_token",
        "expiry_date": 1000000000000,  # 2001
        "token_type": "Bearer",
    }
    cred_file.write_text(json.dumps(expired_data))

    id_tok = make_jwt({"email": "active-keyring@gmail.com"})
    mock_keyring = {
        "access_token": "ya29.active_keyring",
        "refresh_token": "1//refresh",
        "id_token": id_tok,
        "token_type": "Bearer",
        "expiry": "2026-10-25T12:00:00Z",
    }

    with patch("ai_usage_collector.discovery.get_gemini_keyring_credentials", return_value=mock_keyring):
        health = discover_gemini(cred_file)

    assert health["status"] == "valid"
    assert health["detected"] is True
    assert health["metadata"]["email"] == "active-keyring@gmail.com"
    assert health["metadata"]["source"] == "keyring"


def test_discover_gemini_expired_file_with_refresh_token_remains_valid(tmp_path):
    cred_file = tmp_path / "gemini_renewable.json"
    renewable_data = {
        "access_token": "ya29.expired_token",
        "refresh_token": "1//refresh_token_available",
        "expiry_date": 1000000000000,
        "token_type": "Bearer",
    }
    cred_file.write_text(json.dumps(renewable_data))

    with patch("ai_usage_collector.discovery.get_gemini_keyring_credentials", return_value=None):
        health = discover_gemini(cred_file)

    assert health["status"] == "valid"
    assert health["detected"] is True
    assert health["metadata"]["renewable"] is True
    assert "renovável" in health["message"].lower()


def test_discover_gemini_expired_file_without_refresh_token_and_no_keyring_is_expired(tmp_path):
    cred_file = tmp_path / "gemini_truly_expired.json"
    expired_data = {
        "access_token": "ya29.expired_token",
        "expiry_date": 1000000000000,
        "token_type": "Bearer",
    }
    cred_file.write_text(json.dumps(expired_data))

    with patch("ai_usage_collector.discovery.get_gemini_keyring_credentials", return_value=None):
        health = discover_gemini(cred_file)

    assert health["status"] == "session_expired"
    assert health["detected"] is True
    assert "expirada" in health["message"].lower()


def test_discover_gemini_missing_file_falls_back_to_keyring(tmp_path):
    missing_file = tmp_path / "nonexistent.json"
    id_tok = make_jwt({"email": "keyring-only@gmail.com"})
    mock_keyring = {
        "access_token": "ya29.keyring_only",
        "id_token": id_tok,
        "expiry": "2026-10-25T12:00:00Z",
    }

    with patch("ai_usage_collector.discovery.get_gemini_keyring_credentials", return_value=mock_keyring):
        health = discover_gemini(missing_file)

    assert health["status"] == "valid"
    assert health["detected"] is True
    assert health["metadata"]["email"] == "keyring-only@gmail.com"
    assert health["metadata"]["source"] == "keyring"
