"""Auto-discovery of local credentials for AI agents (Claude, Codex, Gemini)."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

DEFAULT_CLAUDE_CREDENTIALS = Path("~/.claude/.credentials.json")
DEFAULT_CODEX_CREDENTIALS = Path("~/.codex/auth.json")
DEFAULT_GEMINI_CREDENTIALS = Path("~/.gemini/oauth_creds.json")


def extract_jwt_identity(token: str | None) -> str | None:
    """Extract identity (email or subject) from a JWT without external libraries."""
    if not token or not isinstance(token, str):
        return None

    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None

        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))

        if isinstance(data, dict):
            return data.get("email") or data.get("sub") or data.get("name")
    except Exception:
        pass

    return None


def parse_timestamp(ts: Any) -> float | None:
    """Parse various timestamp formats into UTC epoch seconds."""
    if ts is None:
        return None

    if isinstance(ts, (int, float)):
        if ts > 1e11:
            return float(ts) / 1000.0
        if ts > 0:
            return float(ts)
        return None

    if isinstance(ts, str):
        ts = ts.strip()
        if not ts or ts.startswith("0001"):
            return None
        try:
            val = float(ts)
            return parse_timestamp(val)
        except ValueError:
            pass

        try:
            clean_ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                pass

    return None


def get_gemini_keyring_credentials(timeout: float = 3.0) -> dict[str, Any] | None:
    """Retrieve active Gemini credentials from system keyring via secret-tool."""
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", "service", "gemini", "username", "antigravity"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None

        raw = proc.stdout.strip()
        if not raw:
            return None

        data: dict[str, Any] = {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            pass

        if not data:
            return {"access_token": raw, "token_type": "Bearer", "raw": raw}

        tok_dict = data.get("token") if isinstance(data.get("token"), dict) else {}
        access_token = tok_dict.get("access_token") or data.get("access_token")
        refresh_token = tok_dict.get("refresh_token") or data.get("refresh_token")
        id_token = data.get("id_token") or tok_dict.get("id_token")
        token_type = tok_dict.get("token_type") or data.get("token_type") or "Bearer"
        expiry = tok_dict.get("expiry") or data.get("expiry_date") or data.get("expiry")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "token_type": token_type,
            "expiry": expiry,
            "raw": data,
        }
    except Exception:
        return None


def discover_claude(credential_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect and validate Claude credentials."""
    path = Path(credential_path or DEFAULT_CLAUDE_CREDENTIALS).expanduser().resolve()

    if not path.exists():
        return {
            "status": "missing_credentials",
            "message": f"Arquivo de credenciais não encontrado ({path})",
            "detected": False,
            "metadata": {"credential_path": str(path)},
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {
            "status": "auth_error",
            "message": f"Falha ao ler credenciais: {e}",
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    if not isinstance(data, dict):
        return {
            "status": "auth_error",
            "message": "Formato de credencial inválido",
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    oauth = data.get("claudeAiOauth")
    access_token = data.get("accessToken")

    if isinstance(oauth, dict) and oauth.get("accessToken"):
        sub_type = oauth.get("subscriptionType")
        tier = oauth.get("rateLimitTier")
        expires_at = oauth.get("expiresAt")

        # Check for expired session
        is_expired = False
        now_ts = datetime.now(timezone.utc).timestamp()
        if isinstance(expires_at, (int, float)):
            exp_sec = expires_at / 1000.0 if expires_at > 1e11 else float(expires_at)
            if exp_sec < now_ts:
                is_expired = True
        elif isinstance(expires_at, str):
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_dt.timestamp() < now_ts:
                    is_expired = True
            except Exception:
                pass

        if is_expired:
            return {
                "status": "session_expired",
                "message": "Sessão Claude expirada. Reautenticação necessária.",
                "detected": True,
                "metadata": {
                    "subscription_type": sub_type,
                    "rate_limit_tier": tier,
                    "expires_at": expires_at,
                    "credential_path": str(path),
                },
            }

        return {
            "status": "valid",
            "message": "Credencial Claude ativa detectada",
            "detected": True,
            "metadata": {
                "subscription_type": sub_type,
                "rate_limit_tier": tier,
                "expires_at": expires_at,
                "credential_path": str(path),
            },
        }
    elif access_token or oauth:
        return {
            "status": "valid",
            "message": "Credencial Claude detectada",
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    return {
        "status": "unauthenticated",
        "message": "Credenciais do Claude ausentes ou não configuradas",
        "detected": True,
        "metadata": {"credential_path": str(path)},
    }


def discover_codex(credential_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect and validate Codex (OpenAI) credentials."""
    path = Path(credential_path or DEFAULT_CODEX_CREDENTIALS).expanduser().resolve()

    if not path.exists():
        return {
            "status": "missing_credentials",
            "message": f"Arquivo de credenciais não encontrado ({path})",
            "detected": False,
            "metadata": {"credential_path": str(path)},
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {
            "status": "auth_error",
            "message": f"Falha ao ler credenciais: {e}",
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    if not isinstance(data, dict):
        return {
            "status": "auth_error",
            "message": "Formato de credencial inválido",
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    tokens = data.get("tokens", {})
    api_key = data.get("OPENAI_API_KEY")
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    id_token = tokens.get("id_token") if isinstance(tokens, dict) else None
    account_id = tokens.get("account_id") if isinstance(tokens, dict) else None
    email = extract_jwt_identity(id_token) if id_token else None

    if access_token or api_key or id_token:
        return {
            "status": "valid",
            "message": "Credencial Codex ativa detectada",
            "detected": True,
            "metadata": {
                "email": email,
                "account_id": account_id,
                "auth_mode": data.get("auth_mode"),
                "last_refresh": data.get("last_refresh"),
                "credential_path": str(path),
            },
        }

    return {
        "status": "unauthenticated",
        "message": "Credenciais do Codex ausentes ou incompletas",
        "detected": True,
        "metadata": {"credential_path": str(path)},
    }


def discover_gemini(credential_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect and validate Gemini (Google) credentials."""
    path = Path(credential_path or DEFAULT_GEMINI_CREDENTIALS).expanduser().resolve()
    now_ts = datetime.now(timezone.utc).timestamp()

    file_data: dict[str, Any] | None = None
    file_read_error: str | None = None

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                file_data = loaded
            else:
                file_read_error = "Formato de credencial inválido"
        except Exception as e:
            file_read_error = f"Falha ao ler credenciais: {e}"

    if file_data is not None:
        access_token = file_data.get("access_token")
        refresh_token = file_data.get("refresh_token")
        id_token = file_data.get("id_token")
        email = extract_jwt_identity(id_token) if id_token else None
        expiry_date = file_data.get("expiry_date") or file_data.get("expiry")

        is_expired = False
        if expiry_date:
            exp_sec = parse_timestamp(expiry_date)
            if exp_sec is not None and exp_sec < now_ts:
                is_expired = True

        # If file token is present and not expired, it is valid
        if access_token and not is_expired:
            return {
                "status": "valid",
                "message": "Credencial Gemini ativa detectada",
                "detected": True,
                "metadata": {
                    "email": email,
                    "expiry_date": expiry_date,
                    "scope": file_data.get("scope"),
                    "token_type": file_data.get("token_type"),
                    "credential_path": str(path),
                },
            }

        # Token in file is expired or missing access_token.
        # Check keyring before reporting expired or unauthenticated.
        keyring_creds = get_gemini_keyring_credentials()
        if keyring_creds and (keyring_creds.get("access_token") or keyring_creds.get("refresh_token")):
            k_id_token = keyring_creds.get("id_token") or id_token
            k_email = extract_jwt_identity(k_id_token) if k_id_token else email
            return {
                "status": "valid",
                "message": "Credencial Gemini ativa detectada via chaveiro",
                "detected": True,
                "metadata": {
                    "email": k_email,
                    "expiry_date": keyring_creds.get("expiry") or expiry_date,
                    "scope": file_data.get("scope"),
                    "token_type": keyring_creds.get("token_type") or file_data.get("token_type"),
                    "credential_path": str(path),
                    "source": "keyring",
                },
            }

        # If no active credential in keyring, but file has refresh_token: session is renewable
        if refresh_token:
            return {
                "status": "valid",
                "message": "Credencial Gemini ativa detectada (sessão renovável)",
                "detected": True,
                "metadata": {
                    "email": email,
                    "expiry_date": expiry_date,
                    "scope": file_data.get("scope"),
                    "token_type": file_data.get("token_type"),
                    "credential_path": str(path),
                    "renewable": True,
                },
            }

        # No refresh token and no keyring token: expired session
        if is_expired:
            return {
                "status": "session_expired",
                "message": "Sessão Gemini expirada. Reautenticação necessária.",
                "detected": True,
                "metadata": {
                    "email": email,
                    "expiry_date": expiry_date,
                    "scope": file_data.get("scope"),
                    "token_type": file_data.get("token_type"),
                    "credential_path": str(path),
                },
            }

        return {
            "status": "unauthenticated",
            "message": "Credenciais do Gemini ausentes ou expiradas",
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    if file_read_error:
        keyring_creds = get_gemini_keyring_credentials()
        if keyring_creds and (keyring_creds.get("access_token") or keyring_creds.get("refresh_token")):
            k_id_token = keyring_creds.get("id_token")
            k_email = extract_jwt_identity(k_id_token) if k_id_token else None
            return {
                "status": "valid",
                "message": "Credencial Gemini ativa detectada via chaveiro",
                "detected": True,
                "metadata": {
                    "email": k_email,
                    "expiry_date": keyring_creds.get("expiry"),
                    "credential_path": str(path),
                    "source": "keyring",
                },
            }
        return {
            "status": "auth_error",
            "message": file_read_error,
            "detected": True,
            "metadata": {"credential_path": str(path)},
        }

    # File does not exist: check keyring as source of Gemini credentials
    keyring_creds = get_gemini_keyring_credentials()
    if keyring_creds and (keyring_creds.get("access_token") or keyring_creds.get("refresh_token")):
        k_id_token = keyring_creds.get("id_token")
        k_email = extract_jwt_identity(k_id_token) if k_id_token else None
        return {
            "status": "valid",
            "message": "Credencial Gemini ativa detectada via chaveiro",
            "detected": True,
            "metadata": {
                "email": k_email,
                "expiry_date": keyring_creds.get("expiry"),
                "credential_path": str(path),
                "source": "keyring",
            },
        }

    return {
        "status": "missing_credentials",
        "message": f"Arquivo de credenciais não encontrado ({path})",
        "detected": False,
        "metadata": {"credential_path": str(path)},
    }


def discover_account(
    provider: str,
    credential_path: str | Path | None = None,
    account_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover credential health for a given provider."""
    provider_lower = provider.lower()
    if provider_lower == "claude":
        res = discover_claude(credential_path)
    elif provider_lower == "codex":
        res = discover_codex(credential_path)
    elif provider_lower == "gemini":
        res = discover_gemini(credential_path)
    else:
        return {
            "status": "error",
            "message": f"Provedor desconhecido: {provider}",
            "detected": False,
            "metadata": {},
        }

    # If file credentials not found or unauthenticated, but account_data contains inline credentials:
    if account_data and res.get("status") in ("missing_credentials", "unauthenticated"):
        token = (
            account_data.get("token")
            or account_data.get("access_token")
            or account_data.get("session_token")
            or account_data.get("api_key")
        )
        if token:
            email = extract_jwt_identity(str(token)) if isinstance(token, str) else None
            return {
                "status": "valid",
                "message": f"Credencial {provider.capitalize()} configurada",
                "detected": True,
                "metadata": {
                    "source": account_data.get("source", "manual"),
                    "email": email,
                },
            }

    return res
