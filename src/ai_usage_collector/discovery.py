"""Auto-discovery of local credentials for AI agents (Claude, Codex, Gemini)."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
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

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    id_token = data.get("id_token")
    email = extract_jwt_identity(id_token) if id_token else None

    if access_token or refresh_token:
        return {
            "status": "valid",
            "message": "Credencial Gemini ativa detectada",
            "detected": True,
            "metadata": {
                "email": email,
                "expiry_date": data.get("expiry_date"),
                "scope": data.get("scope"),
                "token_type": data.get("token_type"),
                "credential_path": str(path),
            },
        }

    return {
        "status": "unauthenticated",
        "message": "Credenciais do Gemini ausentes ou expiradas",
        "detected": True,
        "metadata": {"credential_path": str(path)},
    }


def discover_account(provider: str, credential_path: str | Path | None = None) -> dict[str, Any]:
    """Discover credential health for a given provider."""
    provider_lower = provider.lower()
    if provider_lower == "claude":
        return discover_claude(credential_path)
    elif provider_lower == "codex":
        return discover_codex(credential_path)
    elif provider_lower == "gemini":
        return discover_gemini(credential_path)
    else:
        return {
            "status": "error",
            "message": f"Provedor desconhecido: {provider}",
            "detected": False,
            "metadata": {},
        }
