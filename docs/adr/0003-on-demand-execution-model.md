# Execucao Sob Demanda Sem Polling Continuo

Contexto: Consultas frequentes e desnecessarias em segundo plano podem consumir recursos, poluir sessoes e disparar rate limits ou bloqueios nos portais dos provedores de IA.
Decisao: O coletor operara de forma estritamente sob demanda, acionado exclusivamente quando o usuario clica no botao "Atualizar agora" no Plasmoid (com indicador de progresso assincrono) ou ao iniciar a sessao, sem timers periodicos ou daemons em segundo plano.
Motivo: Respeitar a preferencia do usuario, economizar recursos do sistema e evitar acionamentos indevidos de protecoes anti-bot ou consumo excessivo de cotas de requisicao.
