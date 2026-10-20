# ADR 0006: Alternância Dinâmica de Conta Ativa e Renomeação no Plasmoid

## Contexto

Com a implementação dos perfis isolados (ADR 0005), o usuário pode registrar múltiplas contas para Claude, Codex e Gemini. No entanto, duas limitações de usabilidade foram identificadas no uso real do widget:

1. **Sobreposição Visual em Diálogos do Plasmoid:**
   No diálogo de confirmação de exclusão (`confirmDialog` em `configGeneral.qml`), a presença simultânea de `standardButtons: QQC2.Dialog.Cancel` e botões de ação customizados em `RowLayout` gerou sobreposição direta de botões ("Cancelar" desenhado sobre "Cancelar" e colisão com "Remover Conta"), violando a ergonomia visual do KDE Breeze.

2. **Necessidade de Renomeação Posterior de Contas:**
   Quando uma conta é capturada via `--capture-current` ou `--interactive-login` sem que o usuário tenha digitado um nome customizado prévio, ela recebe um rótulo automático gerado pelo sistema (ex.: `Claude (pro)`, `Codex (user@...)`). Não existia na interface gráfica nem no CLI uma forma de renomear amigavelmente o rótulo da conta sem precisar excluí-la e refazer o fluxo.

3. **Demanda por Alternância Direta de Conta Ativa (Account Switching):**
   Ao atingir o limite temporário de cotas em uma conta de trabalho no terminal (CLI), o usuário quer alternar para outra conta cadastrada que ainda possua cota livre com um único clique no widget desktop, sem precisar abrir o navegador nem realizar novo login OAuth. O CLI oficial sempre lê as credenciais de seus caminhos padrão (`~/.claude/.credentials.json`, `~/.codex/auth.json`, chaveiro/`~/.gemini`), tornando necessário um mecanismo seguro para ativar um perfil isolado nesses caminhos.

## Decisão

1. **Correção dos Diálogos Modais no Plasmoid:**
   - Remover `standardButtons` automáticos de diálogos `QQC2.Dialog` que utilizem botões customizados de ação, evitando duplicidades na barra de botões nativa.
   - Definir layout, paddings e dimensões limpas para os botões `Cancelar`, `Salvar` e `Remover Conta`.

2. **Renomeação de Contas (`--rename-account` e GUI):**
   - Implementar no CLI `ai-usage-collector --rename-account <provider> <account_id> --label <novo_nome>`.
   - Modificar estritamente os campos `label` e `name` no `config.json`, preservando intactos o identificador técnico (`id`), caminhos de credenciais e pasta de perfil isolado.
   - Adicionar botão de edição (ícone `document-edit` / lápis) em cada item da lista de contas em `configGeneral.qml` com diálogo nativo de renomeação.

3. **Mecanismo de Alternância de Conta Ativa no Sistema (`--switch-account` / `--activate-account`):**
   - Implementar no coletor CLI a funcionalidade de sincronização bidirecional:
     a) **Backup da Conta Ativa Atual:** Se houver uma sessão ativa no sistema correspondente a uma conta conhecida nos perfis, sincronizar suas credenciais de volta para a pasta do respectivo perfil (para preservar eventuais tokens renovados automaticamente durante a sessão CLI).
     b) **Aplicação da Nova Conta:** Copiar os artefatos de credencial da conta de destino para os caminhos padrão do sistema (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json` ou chaveiro Secret Service), assegurando permissões Unix estritas `0600`.
     c) **Sincronização de Status:** Atualizar o `status.json` com `isActive: true` na conta ativada e `isActive: false` nas demais.

4. **Interface Visual de Ativação Direta nos Cards do Plasmoid:**
   - No `AccountCard.qml` (visualização principal do widget no desktop/painel), adicionar:
     - Indicador/badge `[✓ Ativa no CLI]` para a conta que estiver ativa no sistema.
     - Botão de ação rápida `[⚡ Ativar no Sistema]` para as contas inativas do mesmo provedor.
   - Ao clicar no botão, executar assincronamente a troca via `DataSource` e atualizar o widget imediatamente.

## Consequências

- **Positivas:**
  - O usuário ganha a capacidade de alternar instantaneamente de conta no terminal através do widget desktop assim que uma cota expirar.
  - Não há perda de tokens renovados pelo CLI graças à sincronização bidirecional antes do switch.
  - Correção definitiva das colisões de botões em diálogos modais do Plasmoid.
  - Personalização completa dos nomes das contas a qualquer momento.
- **Negativas / Riscos:**
  - A troca de credenciais ativas substitui arquivos em `~/.claude` e `~/.codex`. Para mitigar o risco de perda, a gravação utiliza substituição atômica (`save_secure_json`) com backup prévio para o perfil isolado.
