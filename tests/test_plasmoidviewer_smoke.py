"""Smoke no runtime real (plasmoidviewer sob xvfb-run, HOME falso): falha se o log tiver erro de QML nosso."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ("plasmoidviewer", "xvfb-run", "xdotool", "import")
missing = [t for t in TOOLS if shutil.which(t) is None]
pytestmark = pytest.mark.skipif(bool(missing), reason=f"ferramentas ausentes para o smoke do plasmoidviewer: {missing}")


def test_plasmoidviewer_smoke_has_no_qml_errors(tmp_path):
    res = subprocess.run([str(ROOT / "scripts" / "plasmoidviewer-smoke.sh"), str(tmp_path)],
                         env={**__import__("os").environ, "PYTHON": sys.executable, "LANGS": "pt_BR en_US", "FORMS": "horizontal vertical"},
                         capture_output=True, text=True, timeout=240)
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(list(tmp_path.glob("popup_*.png"))) == 4
