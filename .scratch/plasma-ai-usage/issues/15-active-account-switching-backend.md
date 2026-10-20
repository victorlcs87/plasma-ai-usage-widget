## Parent

Closes part of #2

## What to build

Implementar o mecanismo de alternância de conta ativa (Account Switching) no sistema para os três provedores (Claude, Codex e Gemini):

1. **Config**:
   - `set_active_account_in_config(config_data, provider, account_id)`: Marca `"active": true` na conta selecionada e `"active": false` nas demais contas do mesmo provedor.
2. **Capture**:
   - `backup_active_to_profile(provider, config_path)`: Antes da troca, identifica a conta correspondente à sessão ativa do sistema (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`) e sincroniza os arquivos de volta para a pasta do respectivo perfil isolado (para preservar refresh tokens renovados durante a sessão CLI).
   - `activate_profile_to_system(provider, account_id, config_path)`: Copia de forma atômica e com permissões estritas `0600` os arquivos de credenciais da pasta do perfil isolado para os caminhos padrão do sistema (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json` ou chaveiro Secret Service para o Gemini).
3. **Collector & Contract**:
   - Atualizar `build_agent_account_status()` para aceitar `is_active: bool`.
   - No `collect_and_save()`, detectar automaticamente qual conta está ativa no sistema através de comparação das credenciais ativas do sistema com as dos perfis cadastrados, definindo `isActive: true` na conta ativa.
4. **CLI**:
   - Adicionar comando `ai-usage-collector --switch-account <provider> <account_id>` que orquestra o backup prévio, a ativação do novo perfil, a persistência no `config.json`, a coleta atualizada de status e emite feedback em stdout/stderr. Suporte a `--status` para imprimir o JSON atualizado.
5. **Diagnóstico e Correção de Expiração do Gemini**:
   - Investigar e ajustar a renovação ou leitura de sessão do Gemini quando o token do keyring ou arquivo local expirar, evitando falso positivo de `session_expired`.

## Acceptance criteria

- [ ] `set_active_account_in_config()` atualiza flag ativa por provedor.
- [ ] `backup_active_to_profile()` sincroniza credenciais da sessão ativa de volta para o perfil correto.
- [ ] `activate_profile_to_system()` copia credenciais para `~/.claude`, `~/.codex` e `~/.gemini` com permissões `0600`.
- [ ] `ai-usage-collector --switch-account <provider> <account_id>` executa com sucesso e retorna exit code 0.
- [ ] `status.json` inclui campo canônico `isActive: true` para a conta em uso e `isActive: false` para as demais.
- [ ] Detecção automática no `collect_and_save()` identifica a conta ativa mesmo sem chamada explícita de switch.
- [ ] Diagnóstico da autenticação do Gemini para manter a saúde válida ou orientar renovação.
- [ ] Testes automatizados cobrindo switch de Claude, Codex e Gemini, backup prévio e tratamento de erros.

## Blocked by

None (can start immediately)
