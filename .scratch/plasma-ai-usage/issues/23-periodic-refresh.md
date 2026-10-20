# 23: Atualização periódica por provedor com backoff e cache

**Parent:** #8

**What to build:** Implementa a ADR-0007: Intervalo de Atualização configurável por provedor (padrão 300 s, mínimo 60 s) acionado pelo Plasmoid; o coletor aceita atualizar um provedor específico, respeita `retry-after` e aplica backoff exponencial após 429, serve o último resultado válido em cache e marca dados como desatualizados. O contrato informa momento da obtenção, se está desatualizado e a próxima consulta; a UI esmaece dados desatualizados e mostra mensagens claras (login ausente, expirado, limite de requisições). "Atualizar agora" continua funcionando.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Configuração com intervalo por provedor, validando o mínimo.
- [ ] Após 429 com `retry-after`, o provedor não é consultado antes do prazo; cache é servido marcado como desatualizado.
- [ ] Contrato traz `fetched_at`, `stale` e próxima consulta por provedor/Conta.
- [ ] Card esmaece dados desatualizados e mostra quando consultará de novo.
- [ ] "Atualizar agora" ignora o intervalo mas respeita pausa do provedor.
- [ ] Testes pela CLI com respostas HTTP simuladas.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
