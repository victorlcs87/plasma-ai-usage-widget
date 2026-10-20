# Plasma AI Usage Widget

Widget para desktop KDE Plasma 6 que monitora limites, cotas temporais (janela horaria e semanal) e convites de teste gratuito para agentes de IA (Claude, Codex e Gemini) com suporte a multi-contas e gestao grafica completa.

## Language

**Conta**:
Identidade ou perfil de acesso autenticado em um provedor. Um mesmo agente pode ter multiplas contas cadastradas, ativadas ou removidas.
_Avoid_: usuario, perfil, sessao

**Conta Ativa no Sistema**:
A conta cuja credencial esta atualmente aplicada nos caminhos padrao do sistema (`~/.claude/.credentials.json`, `~/.codex/auth.json`, chaveiro/`~/.gemini`), sendo utilizada diretamente por qualquer terminal ou IDE que invoque o agente de IA.
_Avoid_: conta padrao, sessao global, login primario

**Alternancia de Conta (Switch)**:
Operacao atomica que sincroniza a credencial ativa atual de volta para seu perfil de origem e ativa uma nova credencial do perfil selecionado nos diretorios globais do sistema, sem necessidade de reautenticacao no navegador.
_Avoid_: troca de usuario, re-login, swap

**Renomeacao de Conta**:
Alteracao do rotulo amigavel legivel (`label` / `name`) de uma conta previamente cadastrada ou capturada, preservando o identificador interno (`id`) e o diretorio de arquivos de perfil.
_Avoid_: renomear arquivo, mudar id

**Criacao de Conta**:
Acao de cadastrar uma nova credencial ou perfil de acesso diretamente pela interface grafica do Plasmoid ou via comando CLI.
_Avoid_: cadastro manual, edicao de json

**Remocao de Conta**:
Acao de desvincular e excluir uma credencial cadastrada do arquivo de configuracao e da visualizacao do widget.
_Avoid_: desativar, ocultar, desconectar

**Janela Nativa**:
O intervalo temporal e a regra de cota proprios de cada plataforma (ex.: 5 horas no Claude, 3 horas no Codex, diaria/semanal no Gemini), sem forcar padronizacoes artificiais.
_Avoid_: janela generica, timer universal

**Medidor da Janela Semanal**:
Visualizador em barra de progresso com porcentagem de uso acumulado dos ultimos 7 dias e tempo de renovacao do ciclo da semana.
_Avoid_: cota semanal em mensagens, capacidade semanal

**Tempo de Liberacao**:
O momento exato (horario e contagem regressiva) em que a capacidade consumida na janela ativa de uma conta e restaurada pelo provedor.
_Avoid_: reset time, data de expiracao, horario de refresh

**Convite de Teste Gratuito**:
Beneficio promocional concedido pelo provedor que permite presentear terceiros com periodos de teste gratuito ou creditos.
_Avoid_: referral link, link de indicacao, cupom

**Coletor Sob Demanda**:
Script local em Python acionado exclusivamente por solicitacao do usuario (clique em "Atualizar agora"), sem polling continuo em background.
_Avoid_: daemon, worker de fundo, cron job

**Plasmoid**:
Componente de interface grafica nativo do KDE Plasma 6 (desenvolvido em QML/QtQuick) exibido no painel ou na area de trabalho.
_Avoid_: widget, applet, plasmoide
