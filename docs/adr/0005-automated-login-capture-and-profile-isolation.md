# ADR 0005: Captura Automática de Sessões CLI e Isolamento de Perfis de Contas

## Contexto

Na versão anterior do widget, a adição de novas contas exigia que o usuário informasse manualmente o caminho do diretório ou arquivo de credenciais (`--credential-path`). Essa abordagem impunha uma barreira cognitiva excessiva ao usuário, que não conhece nem deve precisar conhecer as estruturas internas de armazenamento de credenciais de cada agente CLI (`~/.claude/.credentials.json`, `~/.codex/auth.json` ou o chaveiro Secret Service do `agy`).

Além disso, quando o usuário faz login em uma nova conta diretamente no terminal usando os comandos oficiais (`claude auth login`, `codex login`), a ferramenta nativa sobrescreve a sessão ativa no diretório padrão (`~/.claude`, `~/.codex`). Sem um mecanismo de isolamento de perfil no widget, a conta anterior seria perdida na coleta seguinte.

Por fim, no diálogo de configurações do Plasmoid, a customização de `contentItem` e `delegate` do `QQC2.ComboBox` colidiu com o tema Breeze do KDE Plasma 6, resultando em sobreposição visual de texto ("Claudede") e supressão dos rótulos dos itens no popup.

## Decisão

1. **Correção Visual do Seletor (ComboBox):**
   Substituir a estilização customizada defeituosa por `PlasmaComponents3.ComboBox` nativo, aderente às diretrizes do KDE Breeze e Kirigami, eliminando a renderização duplicada de texto e restaurando a legibilidade perfeita de nomes e ícones.

2. **Fluxo de Captura de Login Atual (`--capture-current`):**
   Implementar no coletor Python o comando `ai-usage-collector --capture-current <provider> [--name <label>]`:
   - Inspeciona a sessão ativa atual no sistema para o provedor selecionado.
   - Extrai a identidade da conta (e-mail ou ID).
   - Clona os artefatos de autenticação para um diretório de perfil isolado e seguro mantido pelo widget (`~/.config/plasma-ai-usage/profiles/<provider>-<id>/`) com permissões estritas `0600` e `0700`.
   - Registra a conta no `config.json` vinculada a esse diretório isolado, garantindo que alterações futuras no login principal do CLI não corrompam a conta salva.

3. **Fluxo de Login Interativo em Novo Perfil (`--interactive-login`):**
   Implementar no coletor o assistente de login interativo disparável via GUI ou terminal:
   - Aloca um diretório de perfil isolado temporário ou definitivo.
   - Executa o comando de login nativo no ambiente apropriado:
     - Claude: `CLAUDE_CONFIG_DIR=<perfil> claude auth login`
     - Codex: `CODEX_HOME=<perfil> codex login`
     - Gemini: `agy`
   - O widget abre uma janela de terminal (`konsole -e ...` ou fallback para `x-terminal-emulator`/terminal padrão) para que o usuário realize o fluxo OAuth no navegador de forma padrão.
   - Após a conclusão do processo, detecta as credenciais geradas, valida a sessão e persiste a nova conta automaticamente.

4. **Simplificação da Interface Gráfica:**
   O campo "Caminho das Credenciais" deixa de ser obrigatório e é realocado para uma subseção retrátil "Configuração Avançada (Opcional)". A interface principal de adição passa a focar nos botões de ação imediata:
   - "Capturar Sessão Ativa do CLI" (para quando o usuário já logou no terminal);
   - "Fazer Login no Terminal..." (para abrir o assistente de login isolado).

## Consequências

- **Positivas:**
  - O usuário nunca mais precisa adivinhar ou digitar caminhos internos de arquivos.
  - O login em novas contas pode ser feito de forma natural através dos comandos CLI padrão de cada ferramenta.
  - Perfis de múltiplas contas ficam isolados e protegidos contra sobreposição involuntária.
  - Interface do KDE Plasma 6 livre de artefatos visuais e perfeitamente integrada ao tema do sistema.
- **Negativas / Riscos:**
  - A abertura de terminal interativo depende da disponibilidade de um emulador de terminal no ambiente do usuário (mitigado suportando `konsole`, `x-terminal-emulator` e captura passiva via CLI).
