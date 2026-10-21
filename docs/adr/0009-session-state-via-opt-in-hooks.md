# ADR 0009: Estado da Sessao via Hooks Opt-in

Status: accepted

Para exibir o Estado da Sessao (ocupada / aguardando o usuario), no estilo dos aneis animados do Codenotch, decidimos registrar hooks do Claude Code (eventos de envio de prompt, parada e notificacao, mais PostToolUse) que gravam um arquivo de estado local lido pelo Plasmoid. Para o Codex, usamos seu mecanismo de notificacao e os logs de sessao. Os hooks so sao instalados quando o usuario pede explicitamente (`--install-hooks`) e possuem remocao limpa (`--uninstall-hooks`), que preserva os demais hooks e configuracoes do usuario.

## Considered Options

- Heuristica pelo mtime dos logs de sessao: rejeitada porque nao distingue "aguardando o usuario" de "ociosa".
- Instalar os hooks automaticamente: rejeitado porque alterar a configuracao do agente sem consentimento do usuario e invasivo.

## Quarto evento: PostToolUse

Alem dos tres eventos pedidos (UserPromptSubmit = ocupada, Stop = ociosa, Notification = aguardando), o
`--install-hooks` registra PostToolUse = ocupada. Motivos: (1) nao ha evento quando o usuario aprova uma
permissao, entao sem ele a sessao ficaria "aguardando" ate o Stop; (2) serve de batimento, mantendo viva
uma sessao longa. Custo: um processo Python por chamada de ferramenta, medido em cerca de 35 ms (o
interpretador sozinho gasta 9 ms); `python -I -S` funciona, mas nao trouxe ganho mensuravel, entao o
comando usa so `-I`.

## Limitacoes conhecidas

- Esc ou terminal fechado nao disparam Stop. O estado "ocupada" e "aguardando" expira em 5 min sem
  nenhum evento (TTL de ociosa: 30 min). Consequencia inversa: uma unica ferramenta que passe de 5 min
  sem emitir evento deixa de contar como ocupada ate o proximo evento.
- Notification so vira "aguardando" para `permission_prompt` e `elicitation_dialog`; qualquer outro
  tipo, ou tipo ausente, e ignorado. Esses nomes seguem a documentacao do Claude Code e nao foram
  verificados neste repositorio (constante `WAITING_NOTIFICATION_TYPES`).
- Cada Perfil Isolado tem o seu proprio settings.json: rode `--install-hooks` com o `CLAUDE_CONFIG_DIR`
  (absoluto) de cada perfil.
- O hook grava apenas estado, horario, hash do `session_id` e o diretorio de configuracao; nunca o prompt.
- A abertura automatica do Notch pode roubar o foco do teclado; por isso e desligavel.
