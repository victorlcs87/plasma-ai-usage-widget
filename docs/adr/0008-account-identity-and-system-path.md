# ADR 0008: Identidade da Conta e o Caminho do Sistema

Status: accepted (corrige a deteccao da ADR-0006)

Todas as decisoes abaixo valem igualmente para Claude, Codex e Gemini; nenhum provedor tem tratamento de excecao.

A deteccao da Conta Ativa no Sistema comparava tokens, e a configuracao padrao cria em todos os provedores uma conta `default` apontando para o caminho do sistema (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`/chaveiro). O sintoma observado foi no Claude, mas a falha e a mesma nos tres. Por isso ela se comparava consigo mesma e sempre aparecia como ativa. Como o Claude Code rotaciona tokens, os Perfis Isolados deixavam de corresponder. Alem disso, o backup pre-troca era pulado, o que arriscava deslogar o CLI ou perder a credencial anterior.

Decidimos:

1. **Identidade:** cada Conta e reconhecida pela Identidade da Conta e nao pelo token. No Claude, e o `oauthAccount.accountUuid`/`emailAddress` de `~/.claude.json`. No Codex, o `account_id` do JWT. No Gemini, o email Google da conta ativa. A identidade e gravada no Perfil Isolado na captura e em cada troca. A comparacao por token fica so como ultimo recurso.
2. **Caminho do sistema:** o caminho padrao do sistema nunca e uma Conta. Contas legadas que apontam para ele sao migradas para Perfil Isolado. Se ja existir uma Conta com a mesma identidade, as duas sao fundidas, e prevalece o rotulo renomeado pelo usuario.
3. **Backup na troca:** antes de sobrescrever o sistema, a credencial atual sempre volta ao Perfil Isolado da Conta de mesma identidade. Se nenhuma Conta corresponder, ela e capturada como Conta nova, e nenhum login e descartado.
4. **Perfis Orfaos:** sao listados ao usuario, com opcao de reimportar ou excluir mediante confirmacao. Nunca sao apagados automaticamente.
