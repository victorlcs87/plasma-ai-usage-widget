# 38: Caminho de credenciais e API personalizados

**Parent:** #8

**What to build:** Configuração por provedor do caminho de credenciais/pasta alternativa e, para o Claude, URL base e chave de API usadas na consulta de uso (proxy/gateway).

**Blocked by:** 18 (#9)

**Status:** ready-for-agent

- [ ] Caminho alternativo respeitado pela identidade e pela troca.
- [ ] Com URL base personalizada, a consulta usa a chave configurada.
- [ ] Chave armazenada com permissão 0600 e nunca exibida em logs.
- [ ] Testes pela CLI.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
