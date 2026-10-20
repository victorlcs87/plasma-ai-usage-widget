import urllib.error
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_system_path(tmp_path, monkeypatch):
    """Nenhum teste le ou grava o ~/.claude real; testes podem sobrescrever estas variaveis."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "_isolated_claude_system"))


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    """Nenhum teste consulta APIs reais; testes que precisam de HTTP simulam urlopen."""
    def _offline(*_args, **_kwargs):
        raise urllib.error.URLError("rede bloqueada nos testes")

    monkeypatch.setattr(urllib.request, "urlopen", _offline)
