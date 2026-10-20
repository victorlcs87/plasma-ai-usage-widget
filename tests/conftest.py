import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_system_path(tmp_path, monkeypatch):
    """Nenhum teste le ou grava o ~/.claude real; testes podem sobrescrever estas variaveis."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "_isolated_claude_system"))
