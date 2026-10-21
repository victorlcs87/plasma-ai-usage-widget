import urllib.error
import urllib.request

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


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    """Nenhum teste consulta APIs reais; testes que precisam de HTTP simulam urlopen."""
    def _offline(*_args, **_kwargs):
        raise urllib.error.URLError("rede bloqueada nos testes")

    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _offline)


class Notified(list):
    """Transporte D-Bus simulado: registra (resumo, corpo, critico); nunca envia notificacao real."""

    ok = True
    boom = False
    real = None

    def __call__(self, summary, body, critical=False):
        if self.boom:
            raise RuntimeError("transporte quebrou")
        if self.ok:
            self.append((summary, body, critical))
        return self.ok


@pytest.fixture(autouse=True)
def notified(monkeypatch):
    from ai_usage_collector import notifications

    rec = Notified()
    rec.real = notifications.dbus_notify
    monkeypatch.setattr(notifications, "dbus_notify", rec)
    return rec
