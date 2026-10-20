# Spec: Plasma AI Usage Widget

## Problem Statement

O desenvolvedor utiliza diariamente múltiplos agentes de IA (Claude, Codex e Gemini) distribuídos em várias contas de trabalho e pessoais. Cada uma dessas plataformas possui regras próprias de cotas temporais (como o bloco de 5 horas do Claude, 3 horas do Codex e limites diários/semanais do Gemini), além de gerar esporadicamente convites de teste gratuito com links de indicação para terceiros.

Atualmente, não existe visibilidade centralizada no desktop KDE Plasma: para saber se a cota está próxima de estourar, quanto tempo falta para a liberação da próxima janela ou se há convites disponíveis para compartilhar, o usuário precisa interromper seu fluxo de trabalho, abrir navegadores, logar em portais diferentes ou rodar comandos pontuais no terminal.

## Solution

Um Plasmoid nativo para KDE Plasma 6 acoplado a um Coletor Sob Demanda em Python que monitora, calcula e exibe em tempo real no Desktop ou Painel o status consolidado de todas as contas do usuário para Claude, Codex e Gemini.

O sistema respeita a janela nativa de cada plataforma, destacando a capacidade consumida, capacidade disponível e a contagem regressiva para o tempo de liberação da próxima cota, além de exibir badges com convites de teste gratuito que podem ser copiados para a área de transferência com um único clique. A execução é estritamente sob demanda (acionada pelo botão "Atualizar agora" na interface), e o gerenciamento de contas permite adicionar e remover contas diretamente pela interface gráfica ou por arquivo de configuração local.

## User Stories

1. Como usuário do KDE Plasma 6, quero adicionar o Plasmoid ao meu painel ou à minha área de trabalho, para ter visibilidade contínua do uso dos meus agentes de IA.
2. Como usuário com múltiplas contas, quero visualizar todas as contas cadastradas para Claude, Codex e Gemini em um único widget, para não precisar consultar múltiplos painéis web.
3. Como usuário do Claude, quero ver a capacidade consumida e disponível na minha janela nativa de 5 horas, para planejar o envio de prompts pesados sem ser bloqueado no meio de uma tarefa.
4. Como usuário do Claude, quero visualizar o tempo exato e a contagem regressiva de liberação da próxima janela de 5 horas, para saber exatamente quando poderei voltar a programar com o modelo.
5. Como usuário do Codex, quero visualizar o consumo da janela nativa de 3 horas e os limites semanais dos modelos de raciocínio, para controlar o orçamento de requisições avançadas.
6. Como usuário do Codex, quero visualizar o horário de renovação e contagem regressiva de liberação do Codex, para saber quando minhas mensagens serão restabelecidas.
7. Como usuário do Gemini, quero acompanhar os limites nativos diários e semanais de requisições e tokens, para monitorar a cota da minha conta Google.
8. Como usuário com convites de teste gratuito, quero visualizar um badge destacando o número de convites disponíveis em cada conta, para identificar rapidamente oportunidades de compartilhar acessos.
9. Como usuário com convites de teste gratuito, quero clicar no botão de compartilhar do card da conta para copiar o link de convite diretamente para a Área de Transferência (Clipboard), para enviar a colegas sem precisar abrir o navegador.
10. Como usuário preocupado com desempenho e privacidade, quero que a coleta de métricas ocorra estritamente sob demanda ao clicar em "Atualizar agora", para evitar que processos rodem desnecessariamente em segundo plano ou façam polling excessivo.
11. Como usuário interagindo com o widget, quero visualizar um indicador de carregamento (spinner) enquanto a atualização assíncrona é processada, para saber que o sistema está trabalhando sem que a interface gráfica congele.
12. Como usuário, quero visualizar o carimbo de data e hora da última atualização bem-sucedida (ex.: "Atualizado às 09:45"), para saber o grau de recência dos dados exibidos.
13. Como usuário configurando o widget pela primeira vez, quero que o coletor detecte e importe automaticamente as credenciais locais já existentes no sistema (`~/.claude`, `~/.codex` e `~/.gemini`), para que o widget funcione de imediato no primeiro teste sem exigir redigitação de tokens.
14. Como usuário com múltiplas contas no mesmo agente, quero poder cadastrar contas adicionais informando um apelido/identificador amigável e as credenciais correspondentes no arquivo de configuração, para diferenciar facilmente contas pessoais de profissionais.
15. Como usuário gerenciando minhas contas, quero poder remover uma conta cadastrada diretamente pela interface de configurações do widget ou pelo arquivo de configuração, para deixar de monitorar contas desativadas.
16. Como usuário do KDE Plasma, quero que o widget seja responsivo, exibindo um ícone compacto com popup expansível quando posicionado no painel da barra de tarefas, e cartões completos abertos com barras de progresso quando fixado diretamente na Área de Trabalho.
17. Como usuário visualizando o widget no desktop, quero que as barras de progresso mudem de cor conforme o consumo (verde para uso normal, amarelo acima de 70% e vermelho acima de 90%), para identificar visualmente situações críticas em uma fração de segundo.
18. Como usuário que enfrenta proteções de Cloudflare ou captchas em portais web, quero que o sistema permita registrar URLs de convite manuais no arquivo de configuração como fallback, para que o botão de cópia de convite nunca deixe de funcionar mesmo se a extração automática for bloqueada.
19. Como usuário zeloso pela segurança de suas credenciais pessoais, quero que o arquivo de configuração local seja protegido com permissões Unix restritas (`chmod 600`), para que outros usuários da máquina não leiam meus tokens de acesso.
20. Como usuário com muitas contas ativas, quero alternar facilmente a visualização através de abas ou seções retráteis por agente (Claude | Codex | Gemini), para que a interface permaneça limpa, organizada e navegável.

## Implementation Decisions

- **Arquitetura em Duas Camadas Desacopladas (ADR 0001)**:
  - **Coletor CLI Python (`ai-usage-collector`)**: Módulo executável em Python responsável pela ingestão de configurações, leitura e descoberta de credenciais locais (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`), consulta aos logs/APIs e gravação do arquivo de contrato `status.json` em `~/.cache/plasma-ai-usage/status.json`.
  - **Plasmoid KDE Plasma 6 (QML/QtQuick)**: Componente gráfico leve nativo que implementa a interface do usuário, consome o payload JSON de status e delega ações de atualização sob demanda e gerenciamento de contas via execução assíncrona do CLI.

- **Modelo de Domínio e Contrato de Dados (ADR 0002)**:
  - O contrato JSON entre o Coletor e o Plasmoid expõe uma lista tipada de contas agrupadas por agente (`claude`, `codex`, `gemini`).
  - Cada entrada de conta define:
    - Identificador e nome amigável da conta (ex.: `alias` / `label`);
    - Estrutura da Janela Nativa ativa: tipo de janela (ex.: `5h`, `3h`, `daily`), capacidade total, capacidade consumida, capacidade restante, percentual de uso e timestamp de tempo de liberação (com cálculo de segundos restantes);
    - Estrutura da Janela Semanal: consumo acumulado nos últimos 7 dias móveis e data/hora de virada de ciclo;
    - Estrutura de Convites de Teste Gratuito: contador numérico de convites disponíveis e URL de indicação formatada para transferência rápida para o clipboard;
    - Status de saúde da conta: indicação de credencial válida, erro de autenticação ou aviso de necessidade de reautenticação manual.

- **Execução Estritamente Sob Demanda (ADR 0003)**:
  - Nenhum daemon, loop de polling contínuo ou timer systemd periódico deve ser instalado ou executado em segundo plano.
  - A execução do coletor é disparada exclusivamente:
    1. Quando o usuário clica no botão "Atualizar agora" na interface gráfica do Plasmoid;
    2. Na inicialização do Plasmoid (leitura imediata do último cache gerado em disco com atualização assíncrona opcional);
    3. Quando o usuário aciona manualmente o comando CLI pelo terminal.

- **Descoberta de Credenciais e Configuração Multi-Conta Híbrida**:
  - Diretório padrão de configuração em `~/.config/plasma-ai-usage/config.json`.
  - O arquivo segue estrutura com permissão `0600`.
  - Suporta modo `"source": "auto"` para carregar as credenciais padrão já autenticadas pelos CLIs existentes na máquina do usuário.
  - Suporta entradas de contas manuais adicionais, contendo tokens de sessão/cookies e overrides opcionais para links de convites fixos.
  - Operação de remoção de conta exposta via comando CLI `ai-usage-collector --remove-account <provider> <account_id>` que reescreve o `config.json` de forma atômica e atualiza o `status.json`.

- **Interface Gráfica do Plasmoid Plasma 6**:
  - Desenvolvida em QML utilizando componentes Plasma/Kirigami compatíveis com Qt 6 (Plasma 6.8+).
  - Implementa suporte a `Plasmoid.formFactor`:
    - Modo Painel (Taskbar/System Tray): Ícone minimalista com badge resumido e flyout popup ao clicar;
    - Modo Desktop: Visualização expandida em cards de grade com navegação por abas (`Claude`, `Codex`, `Gemini`).
  - Ações diretas:
    - Botão "Atualizar agora" com animação de progresso;
    - Botão de cópia de convite integrado ao Clipboard nativo via `PlasmaCore` / `ClipboardUtils`;
    - Tela de configurações do Plasmoid (`configGeneral.qml`) exibindo lista de contas com botão para exclusão de contas cadastradas.

## Testing Decisions

- **Testes Baseados em Comportamento Externo no Ponto Mais Alto (Highest Seam)**:
  - O ponto de corte principal (seam) para a lógica de negócio é a interface de linha de comando e contrato do Coletor: invocação com fixtures de credenciais/logs locais e validação do payload estruturado `status.json`.
  - Não serão escritos testes acoplados a detalhes internos de implementação de funções privadas; os testes validam o comportamento de ponta a ponta do coletor a partir de entradas de configuração e dados simulados de agentes.
- **Módulos Testados**:
  - Testes do Coletor Python: parsing de logs e extração de janelas nativas de Claude, Codex e Gemini a partir de fixtures locais representativas;
  - Testes de Gerenciamento de Contas: adição, remoção e persistência no arquivo de configuração com validação de permissões `0600`;
  - Testes de Contrato de Cota e Tempo de Liberação: cálculo de percentuais, tempos de liberação em contagem regressiva e fallback gracioso quando um serviço não expõe convites;
  - Validação de Empacotamento do Plasmoid: verificação de integridade estrutural do pacote Plasmoid via ferramentas de validação do KDE Plasma (`kpackagetool6` e validação sintática do manifesto `metadata.json`).
- **Arte Anterior**:
  - Padrões de testes em pytest no repositório local com fixtures isoladas e asserções declarativas em JSON/estruturas de dados.

## Out of Scope

- Compra ou pagamento de novos planos ou contratação de APIs comerciais pay-as-you-go além das contas existentes do usuário.
- Suporte inicial ao editor Cursor ou ferramentas fora da tríade Claude, Codex e Gemini.
- Serviços de polling em segundo plano contínuo ou timers de atualização automática periódica não solicitada.
- Resolução automática de CAPTCHAs complexos ou bypass forçado de proteções anti-bot agressivas em páginas de login web (para isso, adota-se o fallback gracioso de link manual de convite no `config.json`).
- Notificações invasivas e insistentes no desktop sem ação do usuário.

## Further Notes

- O ambiente operacional do usuário é Linux com KDE Plasma 6.8.0 e Python 3.
- As credenciais padrão do Claude Code (`~/.claude/.credentials.json`), Codex (`~/.codex/auth.json`) e Gemini (`~/.gemini/oauth_creds.json`) servem como base imediata para o primeiro teste integrado.
- A distribuição e instalação do Plasmoid será facilitada via script de empacotamento que utiliza `kpackagetool6` para instalação no escopo do usuário (`~/.local/share/plasma/plasmoids/`).
