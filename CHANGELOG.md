# Changelog

## Não lançado

### Novidades
- Atualização do widget pelo Plasmoid (ADR-0014): botão "Update to vX.Y.Z" no popup, no menu do painel, no menu do Notch e na configuração, com Busca de Atualização (`ai-usage-collector --check-update`) e confirmação inline (versão atual → nova, GitHub Releases, sem `sudo`).
- Ordem Coletor → Plasmoid; o `.plasmoid` da tag só é instalado se o SHA256 bater com o embutido no Coletor novo. Ao final, "Reload the widget" pede confirmação e nunca reinicia o plasmashell sozinho.
- Quem está na 1.2.3 ou antes (sem hash embutido) faz a primeira atualização à mão; ver `docs/usage.pt-BR.md`.

## 1.2.4

### Melhorias
- O wheel do Coletor passa a embutir o SHA256 do `.plasmoid` da mesma release (`ai-usage-collector --plasmoid-sha256`), base da futura atualização do widget pelo Plasmoid (ADR-0014).
- O `.plasmoid` é empacotado de forma reprodutível e construído uma única vez; os jobs do GitHub Release e do PyPI reaproveitam o mesmo artefato, e o release falha se o hash faltar ou divergir.

### Mudanças
- O PyPI deixa de receber o sdist (só o wheel puro Python, que carrega o hash).

## 1.2.3

### Melhorias
- Sincronização automática da credencial da Conta Ativa no Sistema para seu Perfil Isolado nos três provedores (Claude, Codex e Gemini) antes da consulta de cota.
- Identificação estrita de Conta por tokens no Claude (`find_account_by_token`), evitando desalinhamentos causados por arquivos de sistema defasados.
- Validação estrita de identidade (`creds_identity`) e fonte no Gemini imediatamente antes de persistir alterações no chaveiro ou em disco.
- Feedback no Plasmoid com orientação contextual para o botão "Renovar sessão" em caso de CLI ativa ou detecção inconclusiva.
- Tratamento resiliente de limites de taxa da API (HTTP 429) como pausa temporária, sem renovação indevida de credenciais.

### Correções
- Eliminação de falso 0% quando o provedor não retorna dados oficiais de cota (`Sem Dados de Cota`), preservando o Histórico de Tokens local.
- Proteção atômica com backups rotacionados e rejeição de regressão de credenciais.

## 1.2.2

### Melhorias
- Botão Renovar sessão por Conta para Claude, Codex e Gemini: tenta renovar e consulta o uso em seguida, preservando as demais Contas.
- Renovação manual da Conta Ativa com a CLI do provedor fechada, conferência de identidade e sincronização do Perfil Isolado. CLI em execução ou detecção inconclusiva produz uma orientação, sem alterar credenciais.
- No Gemini, a tentativa manual não altera a preferência de renovação automática.

### Correções
- Renovação encontra Claude e Codex em `~/.local/bin` quando o PATH do Plasma não inclui esse diretório.
- Detecção de execução do Gemini também reconhece Antigravity e `agy`.

## 1.2.1

### Correções
- Gemini: seleciona apenas cotas do grupo Gemini; limites Claude/GPT não substituem os percentuais ou resets.
- Gemini: prioriza o resumo oficial e usa cotas individuais Gemini como alternativa; semanal ausente permanece sem dados.
- Widget: anéis de consumo contínuos, mantendo as cores de alerta.

## 1.2.0

### Correções
- Gemini: sem token válido ou sem resposta da API, a janela fica sem dados em vez de 0%.
- Gemini: o consumo por modelo combina `retrieveUserQuotaSummary` e `retrieveUserQuota`.
- Intervalo de Atualização padrão e mínimo de 1 h (os provedores respondiam HTTP 429).

### Melhorias
- Instalador do Coletor pelo widget: card com botão "Install collector"/"Update collector", confirmação inline, instala do PyPI a versão exata do widget no venv próprio (`~/.local/share/plasma-ai-usage/venv`) com atalhos em `~/.local/bin`, sem `sudo` e nunca automático. Falhas mostram a causa (ADR-0012).
- O Coletor é publicado no PyPI (`plasma-ai-usage-collector`) por Trusted Publisher (OIDC), só em tag `vX.Y.Z`; o workflow confere tag, `pyproject.toml` e `metadata.json`.
- Licença GPL-3.0-or-later e aviso de marcas (Anthropic, OpenAI, Google) sem afiliação.
- Documentação de distribuição: instalação por três caminhos no README, `docs/store/kde-store.md` e `docs/release-checklist.md`.
- Renovação automática das Contas inativas pelas próprias CLIs (Claude, Codex); a Conta Ativa nunca é tocada (ADR-0013).
- Renovação das Contas Gemini inativas é opt-in, desligada por padrão (usa o app OAuth da Antigravity e lê o segredo do `agy`; pode contrariar os termos do Google): `--set-renew-config --renew-gemini on|off` e controle na aba Geral. Desligada, o `agy` nunca é lido e a Conta vencida só pede novo login.
- Mensagens por estado quando o login vence: renovação pendente, revogado, CLI ou `agy` ausente, tempo esgotado, rede.
- Claude: o extrator aceita o array `limits` além de `five_hour`/`seven_day`.
- Painel: cada item mostra o Logo do Provedor e só o Arco de Horário (Janela Nativa), ocupando a espessura do painel; a escala só reduz. Clicar no item abre o popup com os dois arcos desse provedor no topo; o hover não destaca (ADR-0011).
- Logos de Claude, Codex e Gemini (Simple Icons, CC0) substituem as letras de provedor.
- Gemini: a conta capturada da Antigravity acompanha o arquivo vivo e entende `expiry` ISO.
- Diálogo Renomear Conta e popup dimensionam pelo conteúdo, sem faixa vazia.
- Notch flutuante: a escala vai de 80% a 400% (antes 160%), passo de 10%; o Notch nunca passa da tela. O tamanho das métricas do painel segue 80–160%.

## 1.1.1

### Correções
- Gemini: a conta da CLI Antigravity (`~/.gemini/antigravity-cli/antigravity-oauth-token`, token aninhado) agora é capturada. Ordem das fontes: chaveiro, `oauth_creds.json`, esse arquivo; respeita `GEMINI_CONFIG_DIR`. O arquivo original e o chaveiro nunca são modificados pela captura.
- Notch flutuante: aparecia no monitor errado (índice 0 do Qt) quando o painel do widget ficava em outra tela; a tela agora vem da geometria do containment.

## 1.1.0

Spec 05 (Visual Notch, Inteligência de Limites e Identidade de Conta). Tudo o que envolve hooks, notificações, Notch flutuante e checagem de versão é opt-in.

### Identidade e contas
- Cada Conta é reconhecida pela identidade do provedor (Claude, Codex e Gemini), não pelo token (ADR-0008). O caminho do sistema deixa de ser uma Conta.
- Troca de conta com backup da credencial do sistema no Perfil Isolado certo ou captura como Conta nova, com rollback em falha; Perfis Órfãos listados, reimportáveis e só excluídos com confirmação.
- Caminho de credenciais personalizado por provedor, respeitado também pelo Histórico de Tokens.

### Atualização e dados
- Intervalo de Atualização por provedor (padrão 300 s, mínimo 60 s), `retry-after` e backoff, cache e dados marcados como desatualizados (ADR-0007).
- Janela Nativa com duração do provedor, Ritmo de Uso, Previsão de Esgotamento e nível de alerta (modo ritmo ou limiar).
- Histórico de Tokens (400 dias, exportável em CSV/JSON), detalhamento por modelo e projeto, uso extra do Claude, créditos e modelo do Codex, cota do Gemini por modelo e nota de mudança de limites.

### Interface
- Visual Notch: pílula com Anel Duplo por provedor, estilos Ring, Text e Bar, popup que abre ao passar o mouse e fixa com clique; abas Geral, Painel, Popup, Contas e Notificações.
- Tradução para PT-BR e EN (catálogos em `po/`).
- Saída para Waybar (`--waybar`).

### Opt-in
- **Hooks do Estado da Sessão:** `--install-hooks` (Claude Code e, opcionalmente, Codex) / `--uninstall-hooks` (ADR-0009).
- **Notificações de limite:** pelo `notify-send`; falha avisada uma vez só.
- **Notch flutuante** preso à borda da tela (ADR-0010).
- **Checagem de versão** diária (GitHub Releases e npm), desligável com `--set-update-config --update-check off`.
- Ocultar o widget quando o CLI não está em execução.

### Contrato do `status.json` (versão 5)
Evolução compatível: leitores aceitam as versões 1 a 5 e todos os campos novos são opcionais.
- v2: `usage_details` e `token_history` por Conta.
- v3: `window_seconds` e `elapsed_fraction` nas janelas.
- v4: `fetched_at`, `stale`, `next_check_at`, `fetch_error`, `no_data`, `credential_fingerprint`; `usage_percentage` pode ser `null` sem base confiável.
- v5: `pace`, `forecast` e `alert_level` nas janelas; no topo `alerts`, `notifications`, `updates`, `visibility` e `running_checked_at`; por Conta `session_state`; por provedor `running`.

### Migração e backup
- Ao carregar a configuração, entradas legadas `default` (apontando para o caminho do sistema) migram para Perfil Isolado e se fundem com a Conta de mesma identidade, de forma idempotente e sob `flock`; o histórico por id de Conta (v1) é convertido para identidade (v2).
- Todo perfil sobrescrito com credencial diferente guarda antes `.bak-<timestamp>` (0600, as 5 últimas). O `history.json` corrompido ou de versão mais nova nunca é sobrescrito.
