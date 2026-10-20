# Spec: Medidor Percentual Semanal e Gestão Gráfica de Contas

## Problem Statement

Na versão inicial do widget, a exibição de cota utilizava contadores brutos de mensagens (ex.: "13 / 45 msgs"), o que gerava confusão e ruído visual, além de não fornecer uma visão proporcional e clara sobre o consumo acumulado da semana. Paralelamente, o cadastro de múltiplas contas exigia a edição manual de arquivos de configuração em formato JSON (`config.json`), um processo desconfortável, lento e sujeito a erros de sintaxe para uso diário no ambiente de desktop.

## Solution

Uma reformulação visual e funcional do widget no KDE Plasma 6 e no Coletor Python:
1. **Medidores Percentuais Simétricos:** Substituição dos contadores brutos de mensagens por dois medidores em barras de progresso proporcionais com porcentagem de uso (0 a 100%) e cores dinâmicas:
   - **Medidor da Janela Ativa/Horária:** Porcentagem de uso da janela rotativa (5h no Claude, 3h no Codex, diária no Gemini), volume de tokens e tempo de liberação da próxima cota.
   - **Medidor da Janela Semanal (7 dias):** Porcentagem de uso relativo ao limite semanal, volume acumulado de tokens/mensagens nos últimos 7 dias e data/hora de virada do ciclo semanal.
2. **Gestão Gráfica Completa de Contas no Plasmoid:** Um formulário nativo e intuitivo na tela de configurações do Plasmoid (`configGeneral.qml`) com campos para selecionar o provedor, apelido da conta, caminho das credenciais/pasta e link de convite opcional. A gravação é orquestrada de forma segura via novo comando CLI `ai-usage-collector --add-account`, preservando permissões estritas `0600` e escrita atômica.

## User Stories

1. Como usuário do widget, quero que cada card de conta exiba uma barra de progresso com porcentagem clara para a Janela Ativa (5h/3h/diária), para identificar imediatamente quanto da minha cota horária foi consumida sem precisar interpretar contagens brutas de mensagens.
2. Como usuário do widget, quero que cada card de conta exiba uma barra de progresso com porcentagem para a Janela Semanal (7 dias), para acompanhar visualmente meu consumo acumulado em relação ao teto semanal do meu plano.
3. Como usuário do widget, quero visualizar a contagem regressiva e horário exato de liberação tanto para a janela ativa quanto para a virada do ciclo semanal, para planejar minhas sessões de desenvolvimento.
4. Como usuário do widget, quero que as barras horária e semanal utilizem a mesma dinâmica visual de cores (verde < 70%, amarelo 70-90%, vermelho > 90%), para manter consistência semântica e leitura rápida do estado.
5. Como usuário do widget, quero cadastrar novas contas de IA diretamente na interface gráfica de configurações do Plasmoid, para não precisar abrir terminais nem editar arquivos JSON manualmente.
6. Como usuário adicionando uma conta pela GUI, quero selecionar o provedor (Claude, Codex ou Gemini) a partir de uma caixa de seleção (ComboBox), para evitar erros de digitação no nome do agente.
7. Como usuário adicionando uma conta pela GUI, quero definir um apelido amigável legível (ex.: "Claude - Trabalho" ou "Codex Secundário"), para distinguir minhas contas no desktop.
8. Como usuário adicionando uma conta pela GUI, quero informar o caminho da pasta ou arquivo de credenciais da nova conta com sugestões de caminhos padrão, para facilitar o preenchimento.
9. Como usuário adicionando uma conta pela GUI, quero poder preencher opcionalmente o link do meu convite de teste gratuito, para que ele fique imediatamente disponível para cópia no card correspondente.
10. Como usuário salvando uma nova conta, quero receber feedback visual imediato de sucesso (ou mensagem clara caso algum campo obrigatório esteja faltando) sem que a janela trave.
11. Como usuário após adicionar uma conta pela GUI, quero que o widget no desktop atualize e exiba o card da nova conta instantaneamente, sem precisar reiniciar o Plasmoid ou a sessão do Plasma.
12. Como usuário zeloso pela segurança, quero que o novo comando CLI `--add-account` mantenha permissões Unix estritas `0600` e gravação atômica, para garantir que as credenciais continuem invioláveis.
13. Como usuário gerenciando minhas contas, quero poder tanto adicionar novas contas quanto remover contas existentes na mesma tela gráfica de configurações.
14. Como usuário com contas em diferentes provedores, quero que a listagem gráfica continue agrupada e colorida com as identidades visuais de cada agente.

## Implementation Decisions

- **Arquitetura de Contrato e Backend (`ai-usage-collector`)**:
  - **Sincronização Oficial das APIs de Uso de Claude e Codex**:
    - **Claude (`/api/oauth/usage`)**: Consulta primariamente `https://api.anthropic.com/api/oauth/usage` utilizando o `accessToken` OAuth em `~/.claude/.credentials.json`. Retorna com precisão absoluta de servidor: `five_hour.utilization` (sessão de 5h), `five_hour.resets_at`, `seven_day.utilization` (semanal de 7d) e `seven_day.resets_at`. Em caso de offline, fallback transparente para os logs locais.
    - **Codex (`/backend-api/wham/usage`)**: Consulta primariamente `https://chatgpt.com/backend-api/wham/usage` com `Authorization: Bearer <access_token>` e `ChatGPT-Account-Id: <account_id>` em `~/.codex/auth.json`. Retorna com precisão oficial de servidor: `rate_limit.primary_window.used_percent` (janela rotativa de 5h/18000s e `reset_at`), `rate_limit.secondary_window.used_percent` (janela semanal de 7d/604800s e `reset_at`), `plan_type` e informações de `promo`/convites. Em caso de offline, fallback transparente para o SQLite local `sessions.db`.
    - **Gemini**: Leitura e cálculo analítico de tokens e mensagens a partir do SQLite local em `~/.gemini/antigravity-cli/conversation_summaries.db`, aplicando as cotas horárias e semanais configuradas por plano (com contingência graciosa caso o endpoint do Google Cloud Code venha a ser liberado).
  - **Cálculo da Porcentagem Semanal no Contrato `status.json`**:
    - O modelo de contrato enriquece a seção `weekly_window` com `total_capacity`, `usage_percentage` e `available_capacity`, calculados a partir da capacidade semanal estimada ou configurada para cada plano e agente.
    - Preserva o campo `tokens_used` e `messages_used` para fornecer o contexto de volume.
  - **Novo Comando CLI `ai-usage-collector --add-account`**:
    - Argumentos: `--provider` (obrigatório: `claude`, `codex`, `gemini`), `--label` / `--name` (obrigatório), `--credential-path` / `--dir` (obrigatório), `--invite-url` (opcional), `--total-capacity` (opcional).
    - Suporta `--config-path` e `--cache-path` para isolamento de testes.
    - Executa validação de duplicidade de identificador (gerando ID único seguro em slug), persiste atomicamente no `config.json` via `save_secure_json` (mantendo permissão `0600`), executa a coleta imediata da nova conta e sincroniza o `status.json`.
- **Interface Gráfica do Plasmoid (KDE Plasma 6 / QML)**:
  - **Reformulação de `AccountCard.qml`**:
    - Remoção dos rótulos confusos de "Capacidade: X / Y msgs".
    - Renderização de dois blocos simétricos de medidores:
      1. *Janela Ativa:* Barra de progresso + porcentagem em destaque + badges de tokens + contador regressivo para liberação.
      2. *Janela Semanal:* Barra de progresso + porcentagem semanal em destaque + badges de tokens acumulados + contador para virada de ciclo.
    - Manutenção do badge de convite gratuito com cópia para o clipboard.
  - **Formulário de Adição em `configGeneral.qml`**:
    - Seção expansível / formulário retrátil "+ Adicionar Nova Conta".
    - Controles Kirigami/PlasmaComponents:
      - `QQC2.ComboBox` para seleção do provedor (Claude, Codex, Gemini);
      - `QQC2.TextField` para o Nome/Apelido;
      - `QQC2.TextField` para o Caminho das credenciais (com botão para preencher caminho padrão sugerido);
      - `QQC2.TextField` para URL de convite opcional;
      - Botão "Salvar Conta" que dispara `ai-usage-collector --add-account ...` assincronamente via `Plasma5Support.DataSource` com `shellQuote` e argumentos posicionais seguros.
    - Mensagens em linha (`Kirigami.InlineMessage`) para confirmação de inclusão ou reporte de erros.

## Testing Decisions

- **Seam Principal (CLI do Coletor & Gestão de Contas)**:
  - Testes de subprocesso e integração em pytest cobrindo o comando `--add-account`:
    - Adição bem-sucedida de conta Claude, Codex e Gemini;
    - Validação de argumentos obrigatórios e tratamento de provedor inválido;
    - Verificação de persistência com permissão Unix `0600`;
    - Atualização imediata do `status.json` com os novos dados e percentuais calculados.
- **Seam de Contrato e Cálculo de Métricas**:
  - Testes validando o cálculo de `usage_percentage` e `available_capacity` na `weekly_window` em todos os extratores (Claude, Codex, Gemini).
- **Seam de UI e Empacotamento do Plasmoid**:
  - Testes sintáticos com `qml6` para `AccountCard.qml` e `configGeneral.qml`;
  - Testes de binding e integridade de formulário;
  - Revalidação do pacote Plasmoid via `kpackagetool6`.
- **Arte Anterior**:
  - Suíte existente de 86 testes em `tests/` servindo como baseline contra regressões.

## Out of Scope

- Edição em lote complexa ou reordenação drag-and-drop de cards de contas.
- Métricas financeiras em moeda ou estimativas de custo em dólares (o foco permanece em cotas temporais e janelas nativas de uso).

## Further Notes

- A adição gráfica elimina a barreira de configuração para o usuário, permitindo operar todo o ciclo de vida das contas diretamente pelo KDE Plasma.
