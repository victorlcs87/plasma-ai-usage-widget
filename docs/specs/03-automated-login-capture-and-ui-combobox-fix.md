# Spec: Captura Automática de Login, Perfis Isolados e Correção Visual do Seletor

## Problem Statement

No diálogo de configurações do Plasmoid, os usuários enfrentam duas barreiras críticas:
1. **Falha Visual no Seletor de Provedor:** O seletor de provedor apresenta sobreposição de textos renderizados de forma ilegível ("Claudede") e, ao ser aberto em popup, suprime os nomes dos provedores deixando apenas círculos coloridos, degradando a legibilidade e violando os padrões visuais do KDE Plasma 6.
2. **Barreira Cognitiva na Adição de Contas:** Para adicionar uma conta secundária ou nova conta, o sistema exigia que o usuário soubesse e digitasse caminhos de pastas internas ou arquivos de credenciais (`~/.claude/.credentials.json`, `~/.codex/auth.json`, etc.). Usuários comuns e desenvolvedores não conhecem nem devem precisar conhecer onde os utilitários de linha de comando salvam tokens internos, desejando simplesmente realizar o login pelo CLI ou navegador e ter suas contas capturadas e gerenciadas automaticamente pelo widget. Além disso, sem isolamento de perfis, logar em uma nova conta no CLI substitui a sessão anterior no disco.

## Solution

1. **Correção do Componente Visual de Seleção:** Substituição da estrutura de renderização customizada com conflito de estilo pelo componente nativo de seleção do KDE Plasma (`PlasmaComponents3.ComboBox`), garantindo tipografia nítida, espaçamento adequado e exibição correta dos rótulos de provedores tanto em estado fechado quanto na lista suspensa do tema Breeze.
2. **Captura Automática de Sessões CLI Existentes:** Implementação de um fluxo de captura instantânea com um clique ("Capturar Login Atual do CLI"), que inspeciona a autenticação ativa no sistema para o provedor escolhido, extrai a identidade da conta (e-mail ou ID de usuário), clona as credenciais para um perfil isolado persistente gerido pelo widget com permissões estritas `0600` e registra a conta sem exigir digitação de caminhos.
3. **Assistente de Login Interativo em Perfil Isolado:** Capacidade de iniciar um fluxo de autenticação a partir da interface gráfica que abre o terminal configurado em uma pasta de perfil isolada (usando as variáveis nativas de cada ferramenta como `CLAUDE_CONFIG_DIR` e `CODEX_HOME`), executando o comando oficial de login (`claude auth login`, `codex login`), capturando as credenciais assim que o fluxo no navegador é finalizado e atualizando o widget sem afetar a sessão primária do usuário.
4. **Simplificação da Interface de Configurações:** Reorganização do formulário gráfico para destacar as opções de ação automática ("Capturar Conta Ativa" e "Fazer Login no Terminal"), relegando a entrada manual de diretórios para uma seção opcional retrátil de "Configuração Avançada".

## User Stories

1. Como usuário do widget, quero que o seletor de provedores exiba o nome legível e nítido de cada IA sem sobreposição de textos ou caracteres borrados, para identificar claramente o provedor selecionado.
2. Como usuário do widget, quero que o menu suspenso do seletor liste os nomes completos de todos os provedores acompanhados de suas cores características, para conseguir alternar entre Claude, Codex e Gemini sem adivinhar apenas por cores.
3. Como usuário do widget, quero adicionar uma nova conta simplesmente fazendo login no terminal com o CLI do provedor e clicando em "Capturar Login Atual", para não precisar procurar arquivos de credenciais no disco.
4. Como usuário do widget, quero que o coletor detecte automaticamente o e-mail ou identificador da conta logada no CLI ao capturar uma sessão, para rotular o card com o nome real da minha conta.
5. Como usuário do widget, quero que o sistema clone e armazene as credenciais da conta capturada em um diretório de perfil isolado do widget, para que a conta continue funcionando no widget mesmo se eu logar em outra conta no meu CLI principal.
6. Como usuário do widget, quero clicar em um botão "Fazer Login no Terminal" na tela de configurações, para que uma janela de terminal seja aberta executando o comando oficial de autenticação do agente selecionado.
7. Como usuário autenticando via terminal aberto pelo widget, quero que esse terminal utilize uma pasta de configuração isolada, para que o novo login não sobrescreva a minha conta principal do dia a dia.
8. Como usuário que concluiu a autenticação no navegador/CLI, quero que o widget reconheça automaticamente a conclusão do login, feche o processo interativo e adicione o card ao desktop sem intervenção manual adicional.
9. Como usuário do widget, quero definir um apelido amigável opcional antes de capturar ou iniciar o login, para organizar minhas contas por finalidade (ex: "Claude Pessoal", "Claude Empresa").
10. Como usuário do widget, quero poder cadastrar contas informando um caminho manual customizado apenas se eu desejar, mantendo esse campo escondido sob uma área avançada para não poluir a interface simples.
11. Como usuário capturando uma conta, quero receber uma notificação visual clara de sucesso com o e-mail ou nome da conta capturada, para ter certeza de qual sessão foi incorporada.
12. Como usuário tentando capturar uma conta sem estar logado no CLI correspondente, quero receber uma mensagem de erro clara orientando a realizar o login primeiro, para entender por que a captura falhou.
13. Como usuário zeloso por privacidade, quero que todos os perfis isolados criados pelo widget sejam protegidos com permissões Unix estritas de leitura exclusiva do meu usuário (`0600` e `0700`), para impedir que outros usuários locais acessem meus tokens.
14. Como usuário com múltiplas contas em um mesmo provedor, quero que o sistema diferencie e mantenha ambos os perfis ativos simultaneamente no coletor, permitindo monitorar o consumo das duas contas em cards paralelos no painel do Plasma.
15. Como usuário do widget, quero que a lista de contas na tela de configurações e os cards no desktop atualizem instantaneamente após qualquer captura ou login, sem necessidade de reiniciar o KDE Plasma.

## Implementation Decisions

- **Módulo de Interface do Plasmoid (`configGeneral.qml`):**
  - O seletor de provedores adota o componente oficial `PlasmaComponents3.ComboBox` sem redefinição de template de texto interno, eliminando conflitos de desenho com o tema Breeze.
  - O formulário gráfico é reestruturado em dois blocos de ação primária:
    - *Ação Rápida 1:* Botão "Capturar Sessão Ativa do CLI" que invoca a captura da credencial já existente na máquina.
    - *Ação Rápida 2:* Botão "Fazer Login no Terminal..." que aciona o assistente de login interativo.
  - O campo de caminho manual de credenciais é movido para uma seção colapsável "Opções Avançadas", com preenchimento opcional.
  - As invocações de sistema utilizam `buildCollectorCommand` com `shellQuote` estrito em todos os argumentos.

- **Comandos de CLI no Coletor Python (`ai-usage-collector`):**
  - **Comando `--capture-current`:**
    - Sintaxe: `--capture-current <provider> [--name <label>] [--invite-url <url>]`
    - Inspeciona o caminho padrão do provedor (`~/.claude/.credentials.json`, `~/.codex/auth.json` ou chaveiro via `secret-tool`).
    - Valida se a sessão é válida e ativa.
    - Extrai a identidade do usuário (e-mail ou ID de conta).
    - Cria o diretório de perfil isolado sob `~/.config/plasma-ai-usage/profiles/<provider>-<slug>/` com permissões `0700`.
    - Copia atomicamente os artefatos de credenciais necessários para o diretório de perfil aplicando `0600`.
    - Registra a conta no `config.json` vinculando ao caminho do perfil isolado e dispara a atualização do cache `status.json`.
  - **Comando `--interactive-login`:**
    - Sintaxe: `--interactive-login <provider> [--name <label>]`
    - Cria previamente o diretório de perfil isolado sob a pasta de perfis do widget.
    - Configura as variáveis de ambiente de isolamento específicas de cada ferramenta:
      - Claude: define `CLAUDE_CONFIG_DIR=<diretorio_do_perfil>`.
      - Codex: define `CODEX_HOME=<diretorio_do_perfil>`.
    - Dispara o emulador de terminal disponível no sistema (`konsole -e ...`, com fallbacks para `x-terminal-emulator` ou terminal configurado pelo usuário).
    - Executa o comando oficial de login (`claude auth login`, `codex login`) dentro do ambiente isolado.
    - Monitora a geração dos arquivos de credenciais no diretório do perfil.
    - Após o sucesso, registra a nova conta no `config.json` e sincroniza o `status.json`.

- **Preservação e Segurança de Dados:**
  - Todo diretório de perfil sob `~/.config/plasma-ai-usage/profiles/` é criado com permissão `0700`.
  - Todo arquivo clonado ou gerado tem permissão verificada e forçada em `0600`.
  - O utilitário `save_secure_json` é utilizado para atualizar o `config.json` de forma atômica e resiliente.

## Testing Decisions

- **Critérios de um Bom Teste:**
  - Testar exclusivamente comportamento externo observável via chamadas de CLI e bindings reativos de interface, sem inspecionar detalhes internos de implementação efêmeros.
  - Utilizar mocks estritos de chamadas interativas de terminal e subprocessos nos testes automatizados para garantir execução rápida, idempotente e sem interação humana em ambientes de CI.
- **Módulos Testados:**
  - Módulo CLI (`ai_usage_collector/cli.py` e `account_management`):
    - Testes do comando `--capture-current` para Claude, Codex e Gemini (captura de identidade, clonagem para perfil isolado, permissões `0600`, persistência no `config.json`).
    - Testes de erro ao executar `--capture-current` quando o provedor não está logado ou credenciais estão corrompidas.
    - Testes do assistente `--interactive-login` com injeção de variáveis de ambiente de perfil isolado e validação pós-login.
  - Módulo Plasmoid (`tests/test_plasmoid_packaging.py` e `tests/test_plasmoid_interactive.py`):
    - Validação de ausência de conflitos de renderização no ComboBox de provedor.
    - Presença e acionamento dos novos botões de ação ("Capturar Sessão Ativa" e "Fazer Login no Terminal").
    - Validação de escape e imunidade contra injeção de comandos em todas as chamadas.
- **Arte Prévia no Repositório:**
  - `tests/test_cli_add_account.py` e `tests/test_account_management.py` servem de base para os novos testes de captura de perfil e isolamento.
  - `tests/test_plasmoid_interactive.py` serve de base para os testes de bindings do QML.

## Out of Scope

- Modificação dos binários proprietários dos agentes CLI (`claude`, `codex`, `agy`).
- Gerenciamento de senhas mestras ou bypass de autenticações MFA no navegador (o usuário completa o fluxo no navegador normalmente).
- Sincronização em nuvem de perfis de credenciais para máquinas remotas (o armazenamento é estritamente local).

## Further Notes

- A variável `CLAUDE_CONFIG_DIR` é suportada nativamente pelo CLI oficial do Claude Code desde suas versões iniciais.
- A variável `CODEX_HOME` é suportada nativamente pelo binário compilado do Codex CLI para especificar o diretório de dados e credenciais.
- Para o Gemini (`agy`), a sessão do chaveiro é recuperada via `secret-tool` e preservada no perfil correspondente.
