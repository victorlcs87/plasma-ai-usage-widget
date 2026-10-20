# 07: Backend e Contrato do Medidor Percentual Semanal e CLI `--add-account`

**What to build:** Extensao do coletor Python para consultar primariamente os dados de utilizacao oficiais do servidor do Claude (`https://api.anthropic.com/api/oauth/usage` com o `accessToken` local, obtendo exatamente o % da sessao de 5h e o % semanal de 87% idênticos ao CLI do Claude Code), enriquecer a secao semanal de todos os agentes (`usage_percentage`, `total_capacity` e `available_capacity`), e implementar o comando CLI `ai-usage-collector --add-account` que valida provedores, persiste a nova conta de forma atomica no `config.json` com permissoes estritas `0600` e atualiza o `status.json`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Extrator do Claude consulta `https://api.anthropic.com/api/oauth/usage` usando o `accessToken` existente, mapeando com precisão `five_hour.utilization` (sessão) e `seven_day.utilization` (semanal), com fallback gracioso para os logs locais caso offline.
- [ ] Extratores de Claude, Codex e Gemini enriquecem a `weekly_window` com `usage_percentage`, `total_capacity` e `available_capacity` coerentes com a cota semanal de cada plano.
- [ ] Contrato `status.json` emite os novos campos na secao semanal com validacao pelo schema do contrato.
- [ ] Comando CLI `ai-usage-collector --add-account --provider <prov> --label <nome> --credential-path <caminho>` funcional com flags opcionais `--invite-url` e `--total-capacity`.
- [ ] Validacao contra provedores invalidos e geracao de identificador unico seguro (`slug`).
- [ ] Gravacao atomica segura preservando a permissao `0600` no `config.json` e sincronizacao imediata no cache de status.
- [ ] Testes em pytest cobrindo a integracao da API de uso do Claude com mocks e fallbacks, adicao de contas de todos os provedores, flags do CLI e novos campos semanais.
