# 04: Gestao Multi-Conta e Remocao de Contas via CLI e Configuracao

**What to build:** Suporte completo para configuracao e execucao de multiplas contas por agente (contas pessoais e profissionais com apelidos amigaveis, tokens e convites proprios) e a funcionalidade de remocao de contas (`ai-usage-collector --remove-account <provider> <account_id>`) com sincronizacao atomica em `config.json` e `status.json`.

**Blocked by:** 03: Extratores Nativos Codex e Gemini (Janelas Nativas 3h/Diaria/Semanal, Liberacao e Convites)

**Status:** closed

- [x] Esquema do `config.json` expandido para listas de contas nomeadas por agente (ex.: `claude`, `codex`, `gemini`).
- [x] O coletor itera por todas as contas configuradas e gera o `status.json` contendo a lista completa de contas agrupadas por agente.
- [x] Comando CLI `ai-usage-collector --remove-account <provider> <account_id>` remove a conta indicada de forma atomica no arquivo de configuracao.
- [x] Remocao imediata da conta do `status.json` apos o comando.
- [x] Garantia de que a remocao de uma conta preserva os dados das demais contas e a permissao `0600` do arquivo.
- [x] Testes de comportamento cobrindo adicao de contas secundarias, remocao com sucesso e casos de conta inexistente.
