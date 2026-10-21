# 25: Notificações de limite

**Parent:** #8

**What to build:** O coletor envia notificações do sistema via D-Bus (org.freedesktop.Notifications): limiares configuráveis (padrão 80/95%), aviso antecipado quando a previsão indica esgotamento da Janela Nativa em 30 min ou semanal em 24 h (no máximo uma vez por janela), aviso opcional de reset de limite já sinalizado, e silenciar por provedor. Avisos já dados ficam em cache para não repetir.

**Blocked by:** 24 (#15)

**Status:** ready-for-agent

- [ ] Cada aviso dispara uma única vez por janela, mesmo com várias atualizações.
- [ ] Silenciar um provedor suprime todos os seus avisos.
- [ ] Aviso de reset só para limites antes sinalizados e se habilitado.
- [ ] Configuração dos limiares e opções no Plasmoid.
- [ ] Testes pela CLI com envio D-Bus simulado.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
