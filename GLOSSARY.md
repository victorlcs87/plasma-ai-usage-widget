# Plasma AI Usage Widget

Widget para desktop KDE Plasma 6 que monitora limites, cotas temporais e convites de teste gratuito para agentes de IA (Claude, Codex e Gemini) com suporte a multi-contas e gestao dinamica.

## Language

**Conta**:
Identidade ou perfil de acesso autenticado em um provedor. Um mesmo agente pode ter multiplas contas cadastradas, ativadas ou removidas.
_Avoid_: usuario, perfil, sessao

**Remocao de Conta**:
Acao de desvincular e excluir uma credencial cadastrada do arquivo de configuracao e da visualizacao do widget.
_Avoid_: desativar, ocultar, desconectar

**Janela Nativa**:
O intervalo temporal e a regra de cota proprios de cada plataforma (ex.: 5 horas no Claude, 3 horas no Codex, diaria/semanal no Gemini), sem forcar padronizacoes artificiais.
_Avoid_: janela generica, timer universal

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
