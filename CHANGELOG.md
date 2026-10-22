# Changelog

## Não lançado

### Melhorias
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
