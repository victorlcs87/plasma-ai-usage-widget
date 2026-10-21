# 18: Identidade da Conta — Claude (corrige alternância)

**Parent:** #8

**What to build:** No Claude, o widget passa a reconhecer a Conta Ativa no Sistema pela Identidade da Conta (`oauthAccount.accountUuid`/`emailAddress` do estado do Claude Code), e não pelo token. A configuração padrão deixa de criar contas que apontam para o caminho do sistema; uma migração idempotente converte a entrada legada `default` em Perfil Isolado e funde Contas de mesma identidade (prevalece o rótulo renomeado). A troca segue: identificar credencial do sistema → backup no Perfil Isolado correspondente ou captura como Conta nova → aplicar a escolhida (0600) → regenerar status, com rollback total em falha. Introduz a interface única de identidade por provedor que os tickets de Codex e Gemini reutilizam. Remove a função de troca duplicada e sem uso na raiz do Plasmoid (ADR-0008).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Status marca como ativa a Conta cuja identidade corresponde à credencial do sistema, mesmo após renovação/rotação de access e refresh token.
- [ ] Entrada legada `default` apontando para o caminho do sistema é migrada para Perfil Isolado; duas entradas com a mesma identidade são fundidas preservando o rótulo renomeado; migração é idempotente.
- [ ] Troca A→B→A preserva os tokens renovados no sistema de cada Conta.
- [ ] Credencial desconhecida no sistema é capturada como Conta nova antes de ser sobrescrita.
- [ ] Falha durante a aplicação restaura o sistema ao estado anterior e retorna erro exibido no card.
- [ ] No Plasmoid, clicar em "Ativar" em outra Conta move o selo de ativa para ela.
- [ ] Campo `active` da configuração deixa de ser fonte de verdade.
- [ ] Testes pela CLI cobrindo todos os cenários acima para o Claude.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
