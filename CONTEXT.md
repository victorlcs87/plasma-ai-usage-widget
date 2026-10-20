# Plasma AI Usage Widget

Widget para desktop KDE Plasma 6 que monitora limites, cotas temporais (janela nativa e semanal), ritmo de uso, historico de tokens e convites de teste gratuito para agentes de IA (Claude, Codex e Gemini), com suporte a multi-contas, gestao grafica completa e visual inspirado em um notch escuro.

## Language

### Contas

**Conta**:
Identidade ou perfil de acesso autenticado em um provedor, armazenada em um Perfil Isolado. Um mesmo agente pode ter multiplas contas cadastradas, ativadas ou removidas.
_Avoid_: usuario, perfil, sessao

**Identidade da Conta**:
O identificador estavel atribuido pelo provedor a uma conta (identificador da conta Anthropic, identificador da conta OpenAI ou email Google), que nao muda quando os tokens sao renovados. E o criterio para reconhecer qual Conta esta em uso.
_Avoid_: token, hash da credencial, caminho do arquivo

**Perfil Isolado**:
Copia privada das credenciais de uma Conta, mantida pelo widget fora dos caminhos padrao do sistema.
_Avoid_: pasta da conta, backup

**Perfil Orfao**:
Perfil Isolado existente em disco que nao corresponde a nenhuma Conta cadastrada. Nunca e apagado sem confirmacao do usuario.
_Avoid_: lixo, perfil perdido

**Conta Ativa no Sistema**:
A Conta cuja Identidade corresponde a credencial atualmente aplicada nos caminhos padrao do sistema e usada por qualquer terminal ou IDE que invoque o agente. O caminho padrao do sistema nunca e, por si so, uma Conta.
_Avoid_: conta padrao, sessao global, login primario, default

**Alternancia de Conta (Switch)**:
Operacao atomica que devolve a credencial do sistema ao Perfil Isolado de sua Conta (ou a captura como Conta nova, se desconhecida) e aplica a credencial da Conta escolhida no sistema, sem reautenticacao no navegador.
_Avoid_: troca de usuario, re-login, swap

**Renomeacao de Conta**:
Alteracao do rotulo amigavel de uma Conta, preservando seu identificador interno e seu Perfil Isolado.
_Avoid_: renomear arquivo, mudar id

**Criacao de Conta**:
Acao de cadastrar uma nova credencial ou perfil de acesso diretamente pela interface grafica do Plasmoid ou via comando CLI.
_Avoid_: cadastro manual, edicao de json

**Remocao de Conta**:
Acao de desvincular e excluir uma credencial cadastrada do arquivo de configuracao e da visualizacao do widget.
_Avoid_: desativar, ocultar, desconectar

### Limites e uso

**Janela Nativa**:
O intervalo temporal curto e a regra de cota proprios de cada provedor, com a duracao informada pelo proprio provedor, sem padronizacoes artificiais.
_Avoid_: janela generica, timer universal, janela de 3h

**Medidor da Janela Semanal**:
Indicador da porcentagem de uso acumulado no ciclo semanal do provedor e do tempo ate sua renovacao.
_Avoid_: cota semanal em mensagens, capacidade semanal

**Tempo de Liberacao**:
O momento exato (horario e contagem regressiva) em que a capacidade consumida em uma janela e restaurada pelo provedor.
_Avoid_: reset time, data de expiracao, horario de refresh

**Ritmo de Uso**:
Relacao entre a fracao do limite ja consumida e a fracao da janela ja decorrida; indica se, mantido o ritmo atual, o limite se esgota antes do Tempo de Liberacao.
_Avoid_: velocidade, taxa de consumo

**Previsao de Esgotamento**:
Momento estimado em que um limite chegara a 100% se o Ritmo de Uso recente se mantiver.
_Avoid_: estimativa de fim, ETA

**Historico de Tokens**:
Totais diarios de tokens consumidos por provedor, Conta e modelo, preservados localmente para consulta e exportacao. Token = entrada + saida informados pelo provedor em cada mensagem (no Claude, leituras/escritas de cache ficam fora); o dia e o do fuso local.
_Avoid_: log de uso, estatisticas brutas

**Convite de Teste Gratuito**:
Beneficio promocional concedido pelo provedor que permite presentear terceiros com periodos de teste gratuito ou creditos.
_Avoid_: referral link, link de indicacao, cupom

**Estado da Sessao**:
Situacao de uma sessao do agente em execucao: ocupada, aguardando o usuario ou ociosa.
_Avoid_: status do processo, atividade

### Coleta e interface

**Intervalo de Atualizacao**:
Periodicidade, configuravel por provedor, com que o coletor consulta os limites; respeita pausas impostas pelo provedor e pode ser antecipada pelo usuario com "Atualizar agora".
_Avoid_: polling, daemon, cron job, coletor sob demanda

**Plasmoid**:
Componente de interface grafica nativo do KDE Plasma 6 (desenvolvido em QML/QtQuick) exibido no painel ou na area de trabalho.
_Avoid_: widget, applet, plasmoide

**Notch**:
Linguagem visual do Plasmoid: uma pilula escura compacta que se expande em um painel escuro com os detalhes de uso.
_Avoid_: barra, popup generico

**Anel Duplo**:
Indicador circular de um provedor no Notch: o anel externo representa o Medidor da Janela Semanal e o interno a Janela Nativa, ambos com a marca do tempo decorrido.
_Avoid_: grafico de rosca, gauge
