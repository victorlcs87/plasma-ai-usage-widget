"""SHA256 do .plasmoid da mesma release (ADR-0014).

O release gera `_plasmoid_sha256.py` (não versionado) dentro do wheel; numa árvore de desenvolvimento
ele não existe e o Coletor responde "sem hash". `ai-usage-collector --plasmoid-sha256` imprime o hash.
"""

from __future__ import annotations

import re


def _embedded() -> str | None:
    try:
        from ai_usage_collector._plasmoid_sha256 import PLASMOID_SHA256
    except ImportError:
        return None
    return PLASMOID_SHA256


def plasmoid_sha256() -> str | None:
    """Hex minúsculo de 64 caracteres, ou None se ausente/malformado."""
    value = _embedded()
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None
