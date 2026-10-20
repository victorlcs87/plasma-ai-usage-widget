# 01: Core CLI Coletor, Contrato de Estado e Descoberta Automatica

**What to build:** Um utilitario executavel em linha de comando (`ai-usage-collector`) que inicializa com seguranca a configuracao do usuario (`~/.config/plasma-ai-usage/config.json` com permissoes `0600`), detecta automaticamente credenciais locais pre-existentes dos agentes no ambiente (`.claude`, `.codex`, `.gemini`), e exporta o arquivo de estado canônico padronizado (`~/.cache/plasma-ai-usage/status.json`).

**Blocked by:** None (can start immediately)

**Status:** in-review

- [x] Modulo Python executavel com entrypoint de CLI (`ai-usage-collector --refresh` e `ai-usage-collector --status`) funcional.
- [x] Criacao automatica do diretorio e arquivo `~/.config/plasma-ai-usage/config.json` com permissoes estritas `0600`.
- [x] Auto-descoberta funcional das credenciais padrao dos agentes instalados localmente (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`).
- [x] Geracao do contrato `~/.cache/plasma-ai-usage/status.json` contendo timestamp da atualizacao, status dos agentes e lista estruturada de contas.
- [x] Testes de comportamento no seam da CLI cobrindo criacao de arquivos, permissoes seguras e contrato emitido.
