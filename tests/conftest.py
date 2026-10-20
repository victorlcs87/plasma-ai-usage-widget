import pytest


@pytest.fixture(autouse=True)
def _isolate_system_log_dirs(tmp_path, monkeypatch):
    """Nunca ler logs reais (~/.claude, ~/.codex) no Historico de Tokens durante os testes.

    A configuracao padrao usa caminhos `~/...`, por isso o HOME tambem e isolado.
    """
    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "_sys_claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "_sys_codex"))
    # Caminhos padrao sao resolvidos na importacao (antes do HOME isolado).
    monkeypatch.setattr("ai_usage_collector.history.DEFAULT_CACHE_DIR", tmp_path / "_cache")
