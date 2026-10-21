# ADR 0008: Identidade da Conta e o Caminho do Sistema

Status: accepted (corrige a deteccao da ADR-0006)

Todas as decisoes abaixo valem igualmente para Claude, Codex e Gemini; nenhum provedor tem tratamento de excecao.

A deteccao da Conta Ativa no Sistema comparava tokens, e a configuracao padrao cria em todos os provedores uma conta `default` apontando para o caminho do sistema (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`/chaveiro). O sintoma observado foi no Claude, mas a falha e a mesma nos tres. Por isso ela se comparava consigo mesma e sempre aparecia como ativa. Como o Claude Code rotaciona tokens, os Perfis Isolados deixavam de corresponder. Alem disso, o backup pre-troca era pulado, o que arriscava deslogar o CLI ou perder a credencial anterior.

Decidimos:

1. **Identidade:** cada Conta e reconhecida pela Identidade da Conta e nao pelo token. No Claude, e o `oauthAccount.accountUuid`/`emailAddress` de `~/.claude.json`. No Codex, o `account_id` do JWT. No Gemini, o email Google da conta ativa. A identidade e gravada no Perfil Isolado na captura e em cada troca. A comparacao por token fica so como ultimo recurso.
2. **Caminho do sistema:** o caminho padrao do sistema nunca e uma Conta. Contas legadas que apontam para ele sao migradas para Perfil Isolado. Se ja existir uma Conta com a mesma identidade, as duas sao fundidas, e prevalece o rotulo renomeado pelo usuario.
3. **Backup na troca:** antes de sobrescrever o sistema, a credencial atual sempre volta ao Perfil Isolado da Conta de mesma identidade. Se nenhuma Conta corresponder, ela e capturada como Conta nova, e nenhum login e descartado.
4. **Perfis Orfaos:** sao listados ao usuario, com opcao de reimportar ou excluir mediante confirmacao. Nunca sao apagados automaticamente.

## Consequences

- **Identidade do Claude so por `~/.claude.json`:** o `.credentials.json` nao traz a conta, e sem rede nao ha como distinguir "a Conta A rotacionou os tokens" de "a credencial do sistema e da Conta B com `oauthAccount` defasado". Por isso a igualdade exata de refresh/access token prevalece sobre a identidade, a identidade do sistema nunca e copiada para um Perfil Isolado existente (so na criacao de perfil novo, por captura ou login), pois pode estar defasada, e todo perfil sobrescrito com credencial diferente guarda antes uma copia `.credentials.json.bak-<timestamp>` (0600, as 5 ultimas). No caso residual (identidade defasada e nenhum token coincide) o perfil indicado pela identidade recebe a credencial do sistema e a anterior fica apenas no `.bak`.
- **Claude Code em execucao:** nao ha como travar o `~/.claude.json`. A gravacao e relida logo depois e uma alteracao concorrente aciona o rollback, mas uma escrita entre a releitura e o rollback e sobrescrita.
- **Credencial do sistema como symlink:** as gravacoes seguem o link e escrevem no alvo real. Se o link apontar para um Perfil Isolado, esse perfil e sobrescrito na troca (a credencial anterior fica no `.bak`).
- **Concorrencia:** migracao, troca e captura sao serializadas por `flock` em `config.lock` (0600) no diretorio da configuracao. Renomear, adicionar, remover e o fim do login interativo tambem fazem read-modify-write sob esse lock (recarregando a configuracao dentro dele).
- **Codex e Gemini:** a identidade do Codex (`account_id`) vive no proprio `auth.json`, sem arquivo de estado, e a do Gemini e o email Google (arquivo ou chaveiro, ticket 20); nenhum fica defasado por estado separado.
- **Fusao automatica conservadora:** Contas de mesma identidade so sao fundidas se tambem tiverem o mesmo refresh token; com tokens divergentes ambas permanecem (o usuario remove a duplicata) e nenhuma credencial e sobrescrita.
- **Sem regressao de tokens:** na pre-troca, se o Perfil Isolado tem `expiresAt` mais novo que a credencial do sistema, o perfil e mantido e a credencial do sistema vai para um `.bak-<timestamp>`.
- **Credencial do sistema ilegivel:** a migracao da entrada `default` e adiada ate o arquivo voltar a ser legivel; a entrada nao e apagada.
- **Limitacao residual:** a credencial desconhecida capturada como Conta nova leva a identidade do `~/.claude.json`, que pode estar defasada (rotulo e e-mail errados, tokens no perfil certo).
- **Perfil legado sem `.claude.json`:** nunca recebe identidade. Se os tokens rotacionam, a troca captura os novos como Conta duplicada e A->B->A restaura os tokens velhos (que podem estar revogados); nenhuma credencial se perde, o usuario remove a duplicata.
- **Relogin gera duplicata:** Contas de mesma identidade com tokens divergentes nao sao fundidas; o casamento escolhe o primeiro candidato, entao a ativa pode aparecer como a Conta antiga.
- **Identidade defasada e perfil com identidade:** sem rede, tokens de uma conta podem ser aplicados ao perfil indicado pela identidade defasada; o `.bak` guarda o original.
- **Menores:** a entrada migrada mantem o `id` `default`; rotulo automatico com `subscriptionType` em minusculas nao e reescrito; Codex/Gemini `default` sem backup na troca ate os tickets 19 e 20; `load_config` toma o lock a cada leitura.
