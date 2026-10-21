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

## Caminho leve, mapa de Contas e defasagens

- O plasmoid consulta o estado a cada 5 s pelo entrypoint `ai-usage-session-state` (modulo
  `session_state`, so biblioteca padrao). Ele so existe depois de **reinstalar o pacote**
  (`pip install -e .`); sem ele o plasmoid cai em `ai-usage-collector --session-state` (mais pesado) e
  mostra um aviso no tooltip se a consulta falhar.
- Em cada refresh o coletor grava `session-accounts.json` ao lado do `status.json` (Conta -> diretorios
  de configuracao). O caminho leve usa esse mapa: apos login externo, troca ou remocao de Conta o
  estado fica defasado ate o proximo refresh.
- O hook le o stdin com teto de 2 s (select), nunca ficando preso a uma entrada aberta, e so considera
  campos de nivel raiz do JSON.
- `--uninstall-hooks` (e o install) regrava o settings.json inteiro: preserva chaves e ordem, mas pode
  reindentar o arquivo se o estilo original nao for o detectado.
- `sessionAutoOpen` (abrir o Notch por 5 s) vem **desligado por padrao**: abrir o popup pode roubar o
  foco do teclado, o que nao foi verificado no Plasma real.

## Codex (ticket 36)

O Estado da Sessao do Codex combina duas fontes. **Ocupada** vem so do mtime dos `rollout-*.jsonl` de
`sessions/AAAA/MM/DD` dos 2 dias mais novos (so `stat`: nenhum conteudo de log e lido): escrito ha menos de
20 s = ocupada; sem escrita recente, mas dentro de 30 min = ociosa; senao `unknown`. **Ociosa precisa**
vem do `notify` do `config.toml`, instalado so por `--install-hooks codex` (ou `all`): ao fim do turno ele
grava um registro de estado (hash do `thread-id`), que encerra "ocupada" na hora; escritas do rollout nos
2 s seguintes ao notify nao reabrem "ocupada". Sem o notify, tudo funciona so pelos logs (resposta ate 20 s
mais lenta ao fim do turno). **Aguardando nunca existe para o Codex**: o `notify` so emite fim de turno.

- Instalacao: uma unica linha `notify = [python, -I, session_state.py, --codex-notify, <estado>, <CODEX_HOME>]
  # plasma-ai-usage:codex-notify` no topo do `config.toml` (chave de raiz). Edicao textual e minima, sem
  reserializar; antes de gravar o resultado e relido com `tomllib` e so a chave `notify` pode ter mudado.
  Um `notify` do usuario nunca e sobrescrito (erro claro; encadear e manual). Backup 0600, escrita atomica,
  lock, symlink e deteccao de escrita concorrente reaproveitam os do Claude. Exige Python 3.11+ (`tomllib`).
- O Codex executa o argv sem shell e anexa o JSON como ultimo argumento; so `type` e `thread-id` de raiz
  contam; o comando sai sempre com 0 e sem saida.
- Contrato: `session_state` por Conta Codex, mesmo campo opcional do Claude (sem bump de versao). O mapa
  `session-accounts.json` passou a ser `{provedor: {conta: [diretorios]}}` e `--session-state` /
  `ai-usage-session-state` imprimem `{"claude": {...}, "codex": {...}}`. Mapa no formato antigo vale como
  vazio ate o proximo refresh.
- Verificado na documentacao oficial (2026-10-21): `notify = ["python3", "/caminho/notify.py"]`, "um unico
  argumento JSON", unico evento atual `agent-turn-complete`, campos `thread-id`, `turn-id`, `cwd`,
  `input-messages`, `last-assistant-message` (e `client` quando existe, segundo o codigo-fonte). Layout
  `sessions/AAAA/MM/DD/rollout-*.jsonl` ja era usado pelos extratores deste repositorio.
- NAO verificado (suposicao): a frequencia de escrita no rollout durante um turno (daí o limiar de 20 s,
  `CODEX_BUSY_SECONDS`); que o processo do notify herda `CODEX_HOME` (por isso o diretorio vai no argv); o
  Codex tambem tem hooks de ciclo de vida (`hooks.json`/`[hooks]`) que talvez permitam "aguardando", nao
  avaliados aqui.

### Codex: atencao so com ociosa confirmada (revisao do ticket 36)

- Um turno longo sem escrita no rollout (build, teste, raciocinio) por mais de 20 s aparece como ociosa e,
  na proxima escrita, volta a ocupada. Essa ociosa **nao confirmada** e mostrada, mas nao dispara som nem
  abertura do Notch. So conta a ociosa **confirmada**: o `notify` registrou o fim do turno depois da ultima
  escrita no rollout. O caminho leve imprime `codex_idle_confirmed` (lista de ids de Conta); o QML dispara
  a atencao quando a Conta passa a confirmada. Sem o `notify` instalado, o Codex nunca pede atencao.
- Escritas tardias (mais de 2 s apos o notify) reabrem "ocupada" por alguns segundos e voltam a ociosa sem
  confirmacao: limitacao aceita, sem atencao duplicada.
- A varredura cobre os 7 dias mais novos de `sessions/` (`CODEX_SCAN_DAYS`), para sessoes retomadas. Suposicao
  nao verificada: que `resume` escreve no rollout antigo; se for mais velho que a janela, nunca vira ocupada.
- mtime de rollout mais de 30 s no futuro (relogio adiantado) e ignorado.
