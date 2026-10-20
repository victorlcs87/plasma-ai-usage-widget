# 07: Backend e Contrato do Medidor Percentual Semanal e CLI `--add-account`

**What to build:** Extensao do coletor Python para calcular o percentual de uso da janela semanal (`usage_percentage`, `total_capacity` e `available_capacity`) para todos os agentes (Claude, Codex e Gemini) e implementacao do comando de linha de comando `ai-usage-collector --add-account` que valida provedores suportados, persiste a nova conta de forma atomica no `config.json` com permissoes estritas `0600` e atualiza o `status.json` imediatamente.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Extratores de Claude, Codex e Gemini enriquecem a `weekly_window` com `usage_percentage`, `total_capacity` e `available_capacity` coerentes com a cota semanal de cada plano.
- [ ] Contrato `status.json` emite os novos campos na secao semanal com validacao pelo schema do contrato.
- [ ] Comando CLI `ai-usage-collector --add-account --provider <prov> --label <nome> --credential-path <caminho>` funcional com flags opcionais `--invite-url` e `--total-capacity`.
- [ ] Validacao contra provedores invalidos e geracao de identificador unico seguro (`slug`).
- [ ] Gravacao atomica segura preservando a permissao `0600` no `config.json` e sincronizacao imediata no cache de status.
- [ ] Testes em pytest cobrindo adicao de contas de todos os provedores, flags do CLI e novos campos semanais.
