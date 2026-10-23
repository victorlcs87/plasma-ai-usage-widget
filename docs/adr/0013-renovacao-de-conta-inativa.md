# 0013. Renovacao de Conta inativa

Status: aceita (23/10/2026). Substitui a issue #44.

## Contexto

A Conta inativa guarda uma copia isolada do login em `profiles/`. Ninguem usa a CLI com essa copia, entao o token vence e a Conta aparece como "login vencido" ate o usuario logar de novo no provedor.

## Decisao

O Coletor renova a Conta **inativa** antes de consultar o uso, uma Conta por vez, so no Perfil Isolado:

- **Claude**: `claude auth status` com `CLAUDE_CONFIG_DIR` do perfil.
- **Codex**: `codex app-server` com `CODEX_HOME` do perfil e a chamada `account/read` com `refreshToken: true`. Nao gasta tokens de modelo. `codex login status`, `doctor` e `debug models` nao renovam (teste de 22/10/2026).
- **Gemini**: POST de refresh em `oauth2.googleapis.com/token`. O `client_id` vem do `aud` do `id_token` da propria copia. O `client_secret` e lido **em tempo de execucao** do binario `agy` instalado: por `mmap`, ate 8 candidatos `GOCSPX-`, tentados ate o Google responder HTTP 200. Nunca e embutido no repositorio.

Regras:

- Nunca renovar a Conta Ativa no Sistema (a propria CLI a renova; ver issue #63).
- No maximo uma tentativa por Conta por Intervalo de Atualizacao (minimo agora de 1 h, ADR-0007 ja atualizado). O estado fica em `refresh_state.json`.
- Escrita so no Perfil Isolado. No Gemini a escrita e atomica com permissao 0600 e nunca segue symlink.
- Nenhum segredo em log, `status.json` ou argumento de processo. Falha vira so uma classe (`cli_missing`, `timeout`, `revoked`, `network`, `binary_missing`...), exposta em `renewal` no contrato.
- O Plasmoid mostra uma mensagem por estado a partir dessa classe.

Mudancas relacionadas, na mesma spec:

- Gemini combina `retrieveUserQuotaSummary` e `retrieveUserQuota` para o consumo por modelo.
- Sem token valido ou sem resposta, a janela do Gemini fica "sem dados", nunca 0%.
- O extrator do Claude aceita o array `limits` alem de `five_hour`/`seven_day`. Uma resposta real de 22/10/2026 traz os dois formatos juntos.

## Riscos aceitos

- **Gemini, termos e fragilidade.** `client_id` e `client_secret` sao do app OAuth da Antigravity (`aud` `1071006060591-...`), nao do Gemini CLI oficial (`681255809395-...`). Usa-los pode contrariar os termos do Google. Depende de o `agy` estar instalado e manter o formato do binario. Ler do binario, em vez de embutir, evita redistribuir segredo de app de terceiro.
- **Rotacao do refresh_token.** Renovar pode invalidar copias anteriores do mesmo login. O Codex rotaciona (observado em 22/10/2026). Por isso a renovacao so opera no Perfil Isolado, nunca em copias de teste do mesmo perfil.
- **Endpoints internos.** Os de consumo de Claude, Codex e Gemini nao sao documentados e podem mudar.
- **Conta Ativa fora do escopo.** Renova-la ficou para a issue #63.

## Consequencias

Contas inativas seguem validas enquanto o refresh token viver (cerca de 30 dias) e o Plasma estiver aberto. Sem a CLI no PATH (ou sem o `agy`, no Gemini), a Conta volta a "login vencido" com a causa explicada.
