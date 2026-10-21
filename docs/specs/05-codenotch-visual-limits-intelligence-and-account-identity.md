# Spec 05: Visual Notch, Inteligência de Limites e Identidade de Conta

## Problem Statement

O usuário monitora Claude, Codex e Gemini, com várias Contas, por um Plasmoid que hoje é um ícone genérico com um ponto colorido e um popup de cards em estilo Breeze. Isso gera vários problemas:

1. **A alternância de conta está quebrada em todos os provedores.** O widget marca como Conta Ativa no Sistema uma conta que não está em uso. Ao clicar em "Ativar" na conta certa, nada parece acontecer. A configuração padrão cria, em cada provedor, uma conta `default` que aponta para o próprio caminho do sistema e, por isso, sempre "vence" a detecção. Pior: a troca pula o backup dos tokens renovados e pode deslogar o CLI ou perder a credencial anterior.
2. **Os números não ajudam a decidir.** O widget mostra porcentagens, mas não diz se o ritmo atual esgota o limite antes do Tempo de Liberação, quando isso aconteceria, nem avisa quando um limite se aproxima do fim.
3. **Os dados envelhecem.** O modelo estritamente sob demanda (ADR-0003, agora substituída) deixa o painel desatualizado e impede alertas.
4. **A Janela Nativa do Codex está modelada como 3h**, mas o provedor informa outra duração.
5. **A aparência é genérica.** O usuário quer a identidade visual do Codenotch: uma pílula escura com Anéis Duplos por provedor, que se expande em um Notch escuro.
6. **Faltam funções** que outros widgets de referência (AI Usage Monitor, plasma-claude-usage, limit-rings) oferecem: notificações, Histórico de Tokens, detalhamento por modelo e projeto, uso extra e créditos, Estado da Sessão, estilos de painel, exportação, verificação de atualização e tradução.

## Solution

- **Identidade da Conta (ADR-0008), igual para Claude, Codex e Gemini.** Cada Conta é reconhecida pelo identificador estável do provedor, e não pelo token. O caminho do sistema deixa de ser uma Conta: as entradas legadas `default` migram para um Perfil Isolado e se fundem com a Conta de mesma identidade. Toda troca faz backup da credencial do sistema no Perfil Isolado correto ou, se ela for desconhecida, captura como Conta nova. Os Perfis Órfãos são listados e nunca apagados sem confirmação.
- **Atualização periódica por provedor (ADR-0007).** Há um Intervalo de Atualização para cada provedor. O coletor respeita `retry-after` e backoff, mantém cache, marca dados desatualizados e preserva o "Atualizar agora".
- **Inteligência de limites.** A Janela Nativa usa a duração informada pelo provedor. O coletor calcula o Ritmo de Uso, a Previsão de Esgotamento e a fração de tempo decorrido de cada janela, decide quais notificações enviar e envia.
- **Novos dados.** O coletor passa a gerar o Histórico de Tokens (agregado diário de 400 dias), o detalhamento por modelo e por projeto, o uso extra do Claude e os créditos do Codex, o modelo atual do Codex, a cota do Gemini por modelo e a nota de mudança de limites.
- **Visual Notch.** No painel, uma pílula escura com um Anel Duplo por provedor, representando a Conta Ativa no Sistema. Ficam disponíveis também os estilos Ring, Text e Bar e os modos anel+%, só anel e só %. Ao abrir, um Notch escuro com cards. O popup abre com o mouse por cima e fixa com um clique.
- **Estado da Sessão (ADR-0009).** Hooks opt-in mostram um arco girando quando a sessão está ocupada e um anel âmbar pulsando quando ela está aguardando o usuário.
- **Extras.** Ocultar o widget quando o CLI não está em execução, caminho de credenciais e API personalizados, verificação de atualização (GitHub Releases e npm) e tradução para PT-BR e EN.
- **Opcional, por último.** Um Notch flutuante preso à borda da tela, fora do painel.

## User Stories

### Identidade e alternância de Conta (todos os provedores)

1. Como usuário com várias Contas Claude, quero que o widget marque como ativa exatamente a Conta logada no sistema, para confiar no que vejo.
2. Como usuário com várias Contas Codex, quero a mesma detecção correta da Conta Ativa no Sistema, para trocar de conta com segurança.
3. Como usuário com várias Contas Gemini (arquivo ou chaveiro), quero a mesma detecção correta, para que o comportamento seja igual entre provedores.
4. Como usuário, quero que a Conta continue reconhecida depois que o CLI renovar seus tokens, para que a marcação de ativa não "suma" sozinha.
5. Como usuário, quero clicar em "Ativar" em outra Conta e ver a marcação de ativa mudar para ela, para saber que a troca funcionou.
6. Como usuário, quero que, antes de trocar, a credencial atualmente em uso seja salva no Perfil Isolado da Conta correspondente, para não perder tokens renovados.
7. Como usuário que fez login por fora (ex.: `claude login` com outra conta), quero que essa credencial desconhecida seja capturada como Conta nova antes de ser sobrescrita, para não perder o login.
8. Como usuário com a entrada legada `default`, quero que ela seja migrada automaticamente para um Perfil Isolado, para que o caminho do sistema deixe de ser tratado como uma Conta.
9. Como usuário com duas entradas para a mesma conta, quero que elas sejam fundidas automaticamente, mantendo o rótulo que eu renomeei, para não ver duplicatas.
10. Como usuário, quero ser avisado de Perfis Órfãos e poder reimportá-los ou excluí-los com confirmação, para limpar o disco sem risco.
11. Como usuário, quero que um Perfil Órfão nunca seja apagado sem a minha confirmação, para não perder credenciais.
12. Como usuário, quero que uma troca que falhe deixe o sistema exatamente como estava e mostre o erro, para nunca ficar deslogado.
13. Como usuário Gemini, quero que um token válido no chaveiro prevaleça sobre um arquivo com data de expiração antiga, para não ver "sessão expirada" por engano.
14. Como usuário Gemini, quero que o token do chaveiro continue sendo replicado no arquivo de credenciais de forma atômica e com permissão 0600, para manter os dois consistentes.

### Atualização e confiabilidade dos dados

15. Como usuário, quero que os limites se atualizem sozinhos em intervalos regulares, para ver dados recentes sem clicar.
16. Como usuário, quero configurar o Intervalo de Atualização de cada provedor (padrão de 5 min, mínimo de 60 s), para equilibrar atualidade e carga.
17. Como usuário, quero que o widget respeite as pausas pedidas pelo provedor (429 / `retry-after`) com backoff, para não ser bloqueado.
18. Como usuário, quero continuar vendo os últimos dados conhecidos durante uma pausa ou falha, para não ficar com o painel vazio.
19. Como usuário, quero que dados desatualizados apareçam esmaecidos e com a hora em que foram obtidos, para saber o quanto confiar neles.
20. Como usuário, quero mensagens claras para login ausente, login expirado e limite de requisições, para saber o que fazer.
21. Como usuário, quero manter o "Atualizar agora", para forçar uma leitura imediata.
22. Como usuário, quero que o cartão diga quando os limites serão consultados de novo, para entender a cadência.

### Janelas, ritmo e previsão

23. Como usuário Codex, quero que a Janela Nativa use a duração informada pelo provedor, para que porcentagem e reset sejam corretos.
24. Como usuário de qualquer provedor, quero que a duração da Janela Nativa venha do provedor sempre que disponível, usando a duração fixa só como último recurso.
25. Como usuário, quero ver em cada anel ou barra uma marca de quanto da janela já passou, para comparar com quanto já usei.
26. Como usuário, quero que a cor do indicador mude quando, no Ritmo de Uso atual, o limite esgotaria antes do reset, para agir antes.
27. Como usuário, quero poder trocar a cor por ritmo por limiares fixos (70/90%), caso eu prefira.
28. Como usuário, quero ver a Previsão de Esgotamento de cada limite (Janela Nativa: últimos 30 min; semanal: últimas 24 h), para planejar o trabalho.
29. Como usuário, quero escolher entre ver o uso consumido ou o restante, para ler da forma que prefiro.
30. Como usuário, quero escolher entre contagem regressiva e data/hora do reset, para ler da forma que prefiro.

### Notificações

31. Como usuário, quero uma notificação do sistema quando um limite atingir 80% e 95% (limiares configuráveis), para não ser pego de surpresa.
32. Como usuário, quero um aviso antecipado quando a previsão indicar esgotamento da Janela Nativa em 30 min ou da semanal em 24 h, no máximo uma vez por janela.
33. Como usuário, quero um aviso opcional quando um limite já sinalizado for resetado, para saber que posso voltar a usar.
34. Como usuário, quero silenciar notificações por provedor, para não ser incomodado por um que não uso.
35. Como usuário, não quero receber a mesma notificação repetida a cada atualização, para não ser incomodado.

### Dados adicionais

36. Como usuário, quero ver os tokens de hoje, da semana e do mês por provedor e Conta, para entender meu consumo.
37. Como usuário, quero um gráfico de histórico de 30 dias (diário), 3 meses (semanal) ou 12 meses (mensal), para ver tendências.
38. Como usuário, quero que o Histórico de Tokens seja preservado mesmo que o CLI apague logs antigos, para manter o histórico.
39. Como usuário, quero exportar o histórico diário (até 400 dias) em CSV ou JSON pela CLI, para analisar em outra ferramenta.
40. Como usuário de Waybar ou scripts, quero uma saída de status em JSON com as classes `normal`, `warning` e `critical`, para integrar a outras barras.
41. Como usuário Claude, quero ver o detalhamento de tokens por modelo e por projeto desde o último reset semanal, para saber onde gasto mais.
42. Como usuário Claude, quero ver o uso extra (gasto e limite mensal) quando minha conta o tiver.
43. Como usuário Codex, quero ver meus créditos e o modelo atual quando disponíveis.
44. Como usuário Gemini, quero ver a cota real de cada modelo, para saber qual ainda tenho disponível.
45. Como usuário, quero uma nota no cartão, por três dias, quando um provedor mudar seus limites (janela nova, removida, com duração diferente ou com reset antecipado), para entender mudanças bruscas.
46. Como usuário, quero continuar vendo e copiando os Convites de Teste Gratuito, como hoje.

### Visual Notch — painel

47. Como usuário, quero que o widget no painel seja uma pílula escura com um Anel Duplo por provedor (externo semanal, interno Janela Nativa), para ver tudo de relance.
48. Como usuário com várias Contas, quero que cada anel do painel represente a Conta Ativa no Sistema daquele provedor.
49. Como usuário, quero que o Notch seja sempre escuro, mesmo com tema claro, para manter a identidade visual.
50. Como usuário, quero que a cor de destaque venha da cor de realce do Plasma, com predefinições (rosa, vermelho, laranja, amarelo, verde, teal, azul, índigo, roxo, branco e desligado).
51. Como usuário, quero escolher entre os estilos de painel Pílula (padrão), Ring, Text (% e ponto) e Bar (barras verticais com marcador de tempo).
52. Como usuário, quero escolher entre os modos anel+%, só anel e só %.
53. Como usuário, quero ajustar o tamanho das métricas, a margem e o centro do anel (porcentagem, logo ou logo+%).
54. Como usuário, quero que o widget funcione em painéis horizontais e verticais.
55. Como usuário, quero mostrar, ocultar e reordenar provedores, com a ordem lembrada.
56. Como usuário, quero uma dica (tooltip) com todos os limites e contagens regressivas ao passar o mouse.

### Visual Notch — popup

57. Como usuário, quero que o popup seja um Notch escuro com cards por provedor e Conta (anéis, contagem regressiva, previsão e gráfico), para ver os detalhes num lugar só.
58. Como usuário, quero que o popup abra ao passar o mouse (cerca de 300 ms) e fique fixo com um clique.
59. Como usuário, quero uma opção para voltar ao comportamento padrão do Plasma (abrir só com clique).
60. Como usuário, quero configurar a ordem e a visibilidade dos cards e a opacidade do fundo.
61. Como usuário, quero continuar criando, renomeando, removendo, alternando e capturando Contas e fazendo login interativo pela interface, como hoje.
62. Como usuário, quero que a contagem regressiva do reset avance a cada segundo enquanto o popup estiver aberto.

### Estado da Sessão

63. Como usuário Claude Code, quero instalar, com um comando explícito, hooks que informem o Estado da Sessão, sem que nada seja instalado sem meu pedido.
64. Como usuário, quero remover esses hooks com um comando que preserve os outros hooks e configurações que eu já tenha.
65. Como usuário, quero ver um arco girando no anel enquanto a sessão está ocupada.
66. Como usuário, quero ver o anel âmbar pulsando quando a sessão está aguardando minha resposta.
67. Como usuário, quero que o Notch se abra sozinho por 5 s, com som opcional, quando uma sessão termina ou pede algo.
68. Como usuário Codex, quero o mesmo Estado da Sessão, obtido pelo mecanismo de notificação ou pelos logs do Codex.

### Extras

69. Como usuário, quero opcionalmente ocultar o widget, ou só o uso de um provedor, quando o CLI dele não estiver em execução.
70. Como usuário, quero apontar para um arquivo ou pasta de credenciais diferente do padrão, para usar configurações alternativas.
71. Como usuário com proxy ou gateway, quero configurar uma URL base e uma chave de API personalizadas para as consultas de uso do Claude.
72. Como usuário, quero um selo quando houver nova versão do widget (GitHub Releases) e um ponto quando houver nova versão do Claude Code, do Codex ou do Gemini CLI (npm), com verificação diária que posso desligar.
73. Como usuário, quero a interface em PT-BR ou EN, conforme o idioma do sistema.

### Notch flutuante (opcional, por último)

74. Como usuário, quero opcionalmente um Notch flutuante preso a qualquer uma das quatro bordas da tela, independente do painel.
75. Como usuário, quero arrastar o Notch flutuante ao longo da borda, recentralizar e escolher o tamanho, com posição lembrada para cada borda.
76. Como usuário, quero que o Notch flutuante não se mova quando painéis aparecerem ou sumirem.

## Implementation Decisions

- **Arquitetura mantida (ADR-0001):** o coletor Python gera um contrato de status em JSON, e o Plasmoid QML só o apresenta. Toda decisão (Ritmo de Uso, Previsão de Esgotamento, cor de alerta, dados desatualizados, notificar ou não, identidade, histórico) é calculada no coletor e chega pronta no contrato. O QML não calcula regras de negócio.
- **Módulo de Identidade da Conta:** uma única interface "qual é a identidade desta credencial" para cada provedor.
  - Claude: `oauthAccount.accountUuid` / `emailAddress` do arquivo de estado do Claude Code, ao lado do diretório de configuração.
  - Codex: `account_id` do JWT.
  - Gemini: email da conta Google ativa (arquivo de contas ou chaveiro).
  - A identidade é gravada nos metadados do Perfil Isolado na captura e em cada troca. A comparação por token fica só como último recurso.
  - A detecção da Conta Ativa no Sistema, o backup antes da troca e a captura de conta desconhecida usam todos essa mesma interface.
- **Configuração:** a configuração padrão deixa de criar contas que apontem para o caminho do sistema. Uma migração idempotente roda ao carregar a configuração: converte entradas legadas em Perfil Isolado e funde entradas com a mesma identidade (prevalece o rótulo diferente do automático). O campo `active` deixa de ser fonte de verdade: a detecção é sempre pela identidade.
- **Troca de conta:** ordem de passos, com rollback total em caso de falha:
  1. Ler a credencial do sistema e obter sua identidade.
  2. Fazer backup no Perfil Isolado da Conta correspondente ou capturar como Conta nova.
  3. Aplicar a credencial da Conta escolhida (arquivo com 0600 e, no Gemini, também o chaveiro).
  4. Regenerar o status.
- **Perfis Órfãos:** passam a ser reportados no contrato e na CLI (listar, reimportar e excluir com confirmação explícita).
- **Gemini:** a cópia atômica (0600) do token do chaveiro para o arquivo de credenciais continua. O token que o próprio coletor renovar fica só em memória e nunca é gravado. Um token válido no chaveiro prevalece sobre o arquivo com data de expiração antiga (absorve o escopo da issue #7, já entregue no commit `2472bcc`).
- **Janela Nativa:** a duração vem do provedor (Claude e Codex via janela primária da API de uso; Gemini via resumo de cota). A constante por provedor fica só como fallback da heurística local. O contrato passa a expor a duração da janela em segundos e a fração decorrida.
- **Intervalo de Atualização:** a configuração do Plasmoid ganha um intervalo por provedor (padrão de 300 s, mínimo de 60 s). O Plasmoid aciona o coletor, que recebe o provedor a atualizar. O coletor mantém, por provedor, o estado de pausa e backoff (respeitando `retry-after`) e o último resultado válido em cache. O contrato marca cada provedor e Conta com o momento da obtenção, se o dado está desatualizado e o momento da próxima consulta.
- **Ritmo e previsão:** o contrato expõe, por janela, o Ritmo de Uso (consumido versus decorrido), a Previsão de Esgotamento (Janela Nativa: amostras dos últimos 30 min; semanal: últimas 24 h, a partir do histórico de amostras em cache) e um nível de alerta (`normal`, `warning`, `critical`) segundo o modo escolhido (ritmo ou limiar fixo). No modo ritmo o crítico é fixo em 90% (aviso: ritmo > 1,1 com ≥ 5% da janela decorrida) e os limiares configuráveis só valem no modo limiar. A previsão exige ≥ 3 amostras cobrindo ≥ 5 min; leitura local não tem previsão nem nível.
- **Notificações:** o coletor decide e envia notificações do sistema via D-Bus (org.freedesktop.Notifications). Ele guarda em cache quais avisos já foram dados em cada janela, para não repetir. Limiares, aviso antecipado, aviso de reset e silenciar por provedor são configuráveis.
- **Histórico de Tokens:** o coletor mantém um agregado diário por provedor, Conta e modelo, com retenção de 400 dias, lendo os logs locais de forma incremental (guarda o ponto até onde já leu). Novas opções de CLI permitem exportar em CSV ou JSON e gerar saída JSON no formato Waybar.
- **Dados adicionais no contrato:** detalhamento por modelo e projeto (Claude, desde o último reset semanal, só desta máquina), uso extra (Claude), créditos e modelo atual (Codex), cota por modelo (Gemini) e nota de mudança de limites com validade de 3 dias.
- **Contrato:** evolução compatível. Os campos novos são opcionais e a versão do contrato é incrementada. O Plasmoid tolera campos ausentes.
- **Estado da Sessão:** novos comandos de CLI instalam e removem hooks do Claude Code (envio de prompt, parada e notificação, mais PostToolUse como batimento e para sair de "aguardando" quando o usuário aprova uma permissão; ADR-0009). Os hooks gravam um arquivo de estado local. A remoção preserva os demais hooks do usuário. Para o Codex, usa o mecanismo de notificação ou os logs. O contrato expõe o Estado da Sessão por provedor.
- **Plasmoid — compacto:** nova representação em pílula com um Anel Duplo por provedor (Conta Ativa no Sistema), marca de tempo decorrido, cor pelo nível de alerta, arco e pulso do Estado da Sessão. Estilos Ring, Text e Bar e os modos de exibição como alternativas. Suporte a painéis horizontais e verticais. O percentual dos estilos e modos com % vem da Janela de Destaque: a janela mais urgente (maior nível de alerta do contrato; empate pelo maior percentual). No estilo Text, "só o gráfico" vale como "gráfico e %". Quando a espessura do painel não comporta o estilo (Bar vertical precisa de ~40 px), o widget degrada para Text ou Pílula em vez de cortar; o centro com % cresce o anel para 28 px ou volta ao logo em painéis finos.
- **Plasmoid — popup:** Notch escuro com cards por provedor e Conta. Ordem e visibilidade configuráveis. Mantém todas as ações atuais de Conta. Abre com o mouse por cima (cerca de 300 ms) e fixa com um clique, com opção de usar só o clique. A contagem regressiva avança a cada segundo só com o popup aberto.
- **Cores:** fundo do Notch sempre escuro. A cor de destaque vem da cor de realce do Plasma ou de uma predefinição. As cores de alerta seguem o nível vindo do contrato.
- **Configuração do Plasmoid:** abas Geral, Painel, Popup, Contas e Notificações, todas com KConfigXT.
- **Verificação de atualização:** feita pelo coletor uma vez por dia e desligável. Consulta GitHub Releases do próprio repositório e a versão no npm dos CLIs, comparando com a versão local. O resultado vai no contrato.
- **Ocultar sem CLI:** o coletor informa no contrato se o processo de cada CLI está em execução, e o Plasmoid oculta conforme a configuração.
- **Credenciais e API personalizadas:** campos de configuração por provedor (caminho de credenciais) e, para o Claude, URL base e chave de API usadas na consulta de uso.
- **i18n:** strings do QML com i18n e infraestrutura de catálogo (.pot/.po) com PT-BR e EN completos.
- **Limpeza:** remove a função de troca de conta duplicada e sem uso na raiz do Plasmoid. O card é o único caminho do clique.
- **Notch flutuante (opcional, último):** janela própria presa à borda, com posição por borda, arrastar, recentralizar e tamanho. Reaproveita os mesmos componentes visuais e o mesmo contrato.

## Testing Decisions

- **Ponto único de teste:** a CLI do coletor (`main`) e `collect_and_save`, verificando o `status.json` gerado e os efeitos no sistema de arquivos (Perfis Isolados, caminhos do sistema redirecionados para diretórios temporários por variáveis de ambiente, como já se faz). As chamadas à internet (APIs de uso, GitHub, npm, renovação OAuth) são simuladas com respostas gravadas. O chaveiro e o D-Bus de notificações são simulados no limite do processo.
- **Bons testes verificam comportamento externo:** que Conta o status marca como ativa, que arquivos existem e com que conteúdo e permissão, que notificações foram enviadas. Nunca funções internas.
- **Cobertura obrigatória da Identidade (para Claude, Codex e Gemini, cada um):**
  - Conta `default` legada apontando para o caminho do sistema.
  - Renovação e rotação de refresh token no sistema depois da captura.
  - Troca A→B→A preservando tokens renovados.
  - Credencial desconhecida no sistema capturada antes de ser sobrescrita.
  - Fusão de duplicatas preservando o rótulo renomeado.
  - Perfil Órfão listado e nunca apagado sem confirmação.
  - Rollback quando a aplicação falha.
  - Gemini com chaveiro válido e arquivo com data de expiração antiga.
- **Outros comportamentos:**
  - Duração da Janela Nativa vinda do provedor e o fallback.
  - Backoff após 429 com `retry-after` e dados servidos do cache como desatualizados.
  - Ritmo, previsão e nível de alerta nos dois modos.
  - Notificações por limiar, antecipada e de reset, sem repetição.
  - Histórico incremental, retenção, exportação CSV/JSON e saída Waybar.
  - Instalação e remoção idempotentes dos hooks, preservando hooks existentes.
  - Verificação de atualização.
  - Compatibilidade do contrato com campos novos opcionais.
- **Plasmoid:** continua testado como hoje, por testes de estrutura, registro de configuração e sintaxe dos arquivos QML. Hover, animações, cores e Notch flutuante passam por verificação visual manual com `plasmoidviewer`. Mudanças de UI passam pelo `impeccable`, conforme o fluxo do repositório.
- **Exemplos já existentes:** os testes de troca, captura e renomeação de conta pela CLI, os testes do contrato, os testes dos extratores com respostas simuladas e os testes de empacotamento e interação do Plasmoid.

## Out of Scope

- Novos provedores além de Claude, Codex e Gemini (o Codenotch serve de referência só de aparência).
- Runtimes locais (Ollama, LM Studio), endpoints personalizados genéricos e app móvel.
- Daemon ou serviço systemd do coletor (ADR-0007).
- Merge automático; a entrega é um PR pronto para merge.
- Traduções além de PT-BR e EN (a infraestrutura permite adicionar depois).

## Further Notes

- ADRs relevantes:
  - 0001: coletor e Plasmoid desacoplados.
  - 0005: Perfis Isolados.
  - 0006: alternância, corrigida pela 0008.
  - 0007: atualização periódica, substitui a 0003.
  - 0008: Identidade da Conta.
  - 0009: Estado da Sessão por hooks opt-in.
- A issue #7 já foi entregue (commit `2472bcc`) e fica coberta pelas histórias 13 e 14. Ela será fechada apontando para esta spec.
- As APIs de uso do Claude, do Codex e do Gemini não são oficiais. Uma mudança do provedor deve levar a dados desatualizados com mensagem clara, nunca a um travamento.
- A ordem de implementação sugerida começa pela correção da Identidade da Conta (bug crítico, com risco de perder sessão) e termina no Notch flutuante opcional.
