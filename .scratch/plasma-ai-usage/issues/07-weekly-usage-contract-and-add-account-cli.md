# 07: Backend e Contrato do Medidor Percentual Semanal e CLI `--add-account`

**What to build:** Extensao do coletor Python para consultar primariamente os dados de utilizacao oficiais dos servidores do Claude (`https://api.anthropic.com/api/oauth/usage`), Codex (`https://chatgpt.com/backend-api/wham/usage`) e Gemini/Antigravity (`https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` via token ativo no chaveiro do sistema), enriquecer a secao semanal de todos os agentes (`usage_percentage`, `total_capacity` e `available_capacity`), e implementar o comando CLI `ai-usage-collector --add-account` que valida provedores, persiste a nova conta de forma atomica no `config.json` com permissoes estritas `0600` e atualiza o `status.json`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Extrator do Claude consulta `https://api.anthropic.com/api/oauth/usage` usando o `accessToken` existente, mapeando com precisão `five_hour.utilization` (sessão) e `seven_day.utilization` (semanal), com fallback gracioso para os logs locais caso offline.
- [ ] Extrator do Codex consulta `https://chatgpt.com/backend-api/wham/usage` usando `access_token` e `account_id`, mapeando diretamente `primary_window.used_percent` e `secondary_window.used_percent` (semanal), com fallback gracioso para SQLite local caso offline.
- [ ] Extrator do Gemini consulta `https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` usando o token ativo do `agy` no chaveiro (`secret-tool lookup service gemini username antigravity`), mapeando diretamente as frações restantes e reset de `gemini-5h` e `gemini-weekly`, com fallback gracioso para o SQLite local `conversation_summaries.db`.
- [ ] Contrato `status.json` emite os novos campos na secao semanal com validacao pelo schema do contrato.
- [ ] Comando CLI `ai-usage-collector --add-account --provider <prov> --label <nome> --credential-path <caminho>` funcional com flags opcionais `--invite-url` e `--total-capacity`.
- [ ] Validacao contra provedores invalidos e geracao de identificador unico seguro (`slug`).
- [ ] Gravacao atomica segura preservando a permissao `0600` no `config.json` e sincronizacao imediata no cache de status.
- [ ] Testes em pytest cobrindo a integracao das APIs de uso de Claude, Codex e Gemini com mocks e fallbacks, adicao de contas de todos os provedores, flags do CLI e novos campos semanais.
