# 11: Backend de Captura de Sessão Ativa (`--capture-current`) e Isolamento de Perfis

**What to build:** Implementação no coletor Python do comando `ai-usage-collector --capture-current <provider> [--name <label>] [--invite-url <url>]`, que detecta a autenticação ativa do sistema para o provedor selecionado (Claude, Codex ou Gemini), extrai a identidade/e-mail real da conta, clona e isola os artefatos de credenciais sob `~/.config/plasma-ai-usage/profiles/<provider>-<id>/` com permissões Unix estritas `0600`/`0700`, registra atomicamente no `config.json` e atualiza o `status.json`.

**Blocked by:** None (can start immediately)

**Status:** completed

- [x] Comando CLI `ai-usage-collector --capture-current <provider>` implementado e suportando `--name` e `--invite-url`.
- [x] Extração automática da identidade do usuário (e-mail, orgId, account_id) da sessão ativa de Claude, Codex e Gemini.
- [x] Criação do diretório de perfil isolado sob `profiles/` com permissão Unix estrita `0700`.
- [x] Cópia e persistência atômica das credenciais ativas para a pasta do perfil isolado com permissão `0600`.
- [x] Registro automático da nova conta no `config.json` apontando para o caminho do perfil isolado.
- [x] Execução de coleta imediata da nova conta com atualização do cache `status.json`.
- [x] Mensagens de erro claras quando o provedor selecionado não possuir sessão ativa ou credencial válida no sistema.
- [x] Bateria de testes em pytest cobrindo Claude, Codex e Gemini com mocks herméticos de arquivos de sessão e validações de segurança.
