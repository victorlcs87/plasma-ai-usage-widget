# 0013. Renovacao de Conta inativa

Status: aceita (23/10/2026). Substitui a issue #44.

## Contexto

A Conta inativa guarda uma copia isolada do login em `profiles/`. Ninguem usa a CLI com essa copia, entao o token vence e a Conta aparece como "login vencido" ate o usuario logar de novo no provedor.

## Decisao

O Coletor renova a Conta **inativa** antes de consultar o uso, uma Conta por vez, so no Perfil Isolado:

- **Claude**: `claude auth status` com `CLAUDE_CONFIG_DIR` do perfil.
- **Codex**: `codex app-server` com `CODEX_HOME` do perfil e a chamada `account/read` com `refreshToken: true`. Nao gasta tokens de modelo. `codex login status`, `doctor` e `debug models` nao renovam (teste de 22/10/2026).
- **Gemini** (**opt-in, desligada por padrao**, decisao de 23/10/2026 apos o security-review): POST de refresh em `oauth2.googleapis.com/token`. O `client_id` vem do `aud` do `id_token` da propria copia. O `client_secret` e lido **em tempo de execucao** do binario `agy` instalado: por `mmap`, ate 8 candidatos `GOCSPX-`, tentados ate o Google responder HTTP 200. Nunca e embutido no repositorio.

Opt-in do Gemini: a opcao `renew.gemini` do `config.json` comeca desligada. Liga-se em Configuracao > Geral ou com `--set-renew-config --renew-gemini on` (`off` desliga). Desligada, o Coletor nao faz `which agy`, nao le o binario e nao chama o endpoint de token do Google; a Conta inativa vencida mostra `renewal.error = "disabled"` e o Plasmoid pede para reativa-la (modo so avisar). Claude e Codex nao dependem da opcao.

Regras:

- Nunca renovar automaticamente a Conta Ativa no Sistema. A exceção manual abaixo atende à issue #63.
- No maximo uma tentativa por Conta por Intervalo de Atualizacao (minimo agora de 1 h, ADR-0007 ja atualizado). O estado fica em `refresh_state.json`.
- Escrita so no Perfil Isolado. No Gemini a escrita e atomica com permissao 0600 e nunca segue symlink.
- Nenhum segredo em log, `status.json` ou argumento de processo. Falha vira so uma classe (`cli_missing`, `timeout`, `revoked`, `network`, `binary_missing`...), exposta em `renewal` no contrato.
- O Plasmoid mostra uma mensagem por estado a partir dessa classe.

Mudancas relacionadas, na mesma spec:

- Gemini combina `retrieveUserQuotaSummary` e `retrieveUserQuota` para o consumo por modelo.
- Sem token valido ou sem resposta, a janela do Gemini fica "sem dados", nunca 0%.
- O extrator do Claude aceita o array `limits` alem de `five_hour`/`seven_day`. Uma resposta real de 22/10/2026 traz os dois formatos juntos.

## Riscos aceitos

- **Gemini, termos e fragilidade (motivo do opt-in).** `client_id` e `client_secret` sao do app OAuth da Antigravity (`aud` `1071006060591-...`), nao do Gemini CLI oficial (`681255809395-...`). Usa-los pode contrariar os termos do Google. Depende de o `agy` estar instalado e manter o formato do binario. Ler do binario, em vez de embutir, evita redistribuir segredo de app de terceiro.
- **Rotacao do refresh_token.** Renovar pode invalidar copias anteriores do mesmo login. O Codex rotaciona (observado em 22/10/2026). Por isso a renovacao so opera no Perfil Isolado, nunca em copias de teste do mesmo perfil.
- **Endpoints internos.** Os de consumo de Claude, Codex e Gemini nao sao documentados e podem mudar.
- **Conta Ativa fora do escopo.** Renova-la ficou para a issue #63.

## Consequencias

Contas inativas seguem validas enquanto o refresh token viver (cerca de 30 dias) e o Plasma estiver aberto. Sem a CLI no PATH (ou sem o `agy`, no Gemini), a Conta volta a "login vencido" com a causa explicada.

## Complemento — renovação manual por Conta (24/10/2026)

O botão Renovar sessão e `--renew-account PROVEDOR ID` autorizam uma tentativa para uma Conta, seguida da consulta de uso. A coleta preserva as demais Contas no cache e não altera a Conta Ativa no Sistema.

Na Conta Ativa, a tentativa exige que o processo do provedor esteja comprovadamente parado. É serializada com captura/alternância por `config_lock`, confere a identidade atual antes e depois e sincroniza a credencial renovada para o Perfil Isolado. Claude e Codex usam seus mecanismos de CLI; Gemini usa o mesmo mecanismo OAuth já existente e persiste no armazenamento de origem (arquivo plano, Antigravity aninhado ou chaveiro). Não há token em argumentos, saída ou status.

A tentativa manual do Gemini não liga a opção de renovação automática. As regras automáticas de confinamento ao Perfil Isolado continuam valendo. Sessão revogada ainda requer login interativo; processo em execução ou identidade inconclusiva resulta em orientação, sem tentar renovar.

## Complemento — recuperação automática da Conta Ativa Claude (24/10/2026)

Após sincronizar a credencial do sistema com o Perfil Isolado, a coleta Claude tenta renovar a Conta Ativa quando o access token está ausente ou vencido, ou quando a API rejeita a autenticação. A tentativa usa as mesmas guardas da renovação manual: `config_lock`, CLI comprovadamente parada, identidade conferida antes e depois, e sincronização do resultado com o Perfil Isolado. O resultado é registrado em `refresh_state.json`, limitado a uma tentativa por Conta por Intervalo de Atualização e ao orçamento de renovação do ciclo. Após sucesso decorrente de rejeição da API, uma única nova consulta é feita. Falhas de rede, limite de requisições e resposta inválida não acionam renovação. Se a recuperação falhar, a cota fica sem dados ou usa cache desatualizado da mesma identidade; o diagnóstico expõe apenas a classe do erro.
