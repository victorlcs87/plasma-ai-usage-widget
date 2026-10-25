"""Hash do .plasmoid embutido no wheel do Coletor (ADR-0014): leitura pelo Coletor e checagem do release."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from ai_usage_collector import cli, plasmoid_hash

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK = REPO_ROOT / "scripts" / "check-release-hash.py"
MODULE = "ai_usage_collector/_plasmoid_sha256.py"


def _release(tmp_path, content: bytes = b"zip-bytes", embedded: str | None = "auto"):
    """Cria .plasmoid e wheel falsos; `embedded` None omite o módulo do hash."""
    plasmoid = tmp_path / "x.plasmoid"
    plasmoid.write_bytes(content)
    wheel = tmp_path / "plasma_ai_usage_collector-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("ai_usage_collector/__init__.py", "")
        if embedded is not None:
            digest = hashlib.sha256(content).hexdigest() if embedded == "auto" else embedded
            zf.writestr(MODULE, f'PLASMOID_SHA256 = "{digest}"\n')
    return plasmoid, wheel


def _check(plasmoid, wheel):
    return subprocess.run([sys.executable, str(CHECK), str(plasmoid), str(wheel)], capture_output=True, text=True)


def test_check_ok(tmp_path):
    assert _check(*_release(tmp_path)).returncode == 0


def test_check_fails_when_hash_missing_from_wheel(tmp_path):
    r = _check(*_release(tmp_path, embedded=None))
    assert r.returncode == 1 and "ausente" in r.stderr


def test_check_fails_when_hash_diverges_from_zip(tmp_path):
    r = _check(*_release(tmp_path, embedded="0" * 64))
    assert r.returncode == 1 and "diverge" in r.stderr


def test_collector_reads_embedded_hash(monkeypatch, capsys):
    monkeypatch.setattr(plasmoid_hash, "_embedded", lambda: "ab" * 32)
    assert cli.main(["--plasmoid-sha256"]) == 0
    assert capsys.readouterr().out == "ab" * 32 + "\n"


def test_collector_without_embedded_hash_fails(monkeypatch, capsys):
    monkeypatch.setattr(plasmoid_hash, "_embedded", lambda: None)
    assert cli.main(["--plasmoid-sha256"]) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("bad", ["", "xyz", "AB" * 32, "a" * 63])
def test_malformed_hash_is_treated_as_missing(monkeypatch, bad):
    monkeypatch.setattr(plasmoid_hash, "_embedded", lambda: bad)
    assert plasmoid_hash.plasmoid_sha256() is None
