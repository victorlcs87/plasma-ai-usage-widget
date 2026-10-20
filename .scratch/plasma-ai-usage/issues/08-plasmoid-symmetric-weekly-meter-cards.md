# 08: Reformulacao Visual dos Cards no Plasmoid com Medidores Simetricos Horario/Semanal

**What to build:** Redesenho completo dos cards de contas no Plasmoid (`AccountCard.qml`), substituindo os contadores brutos de mensagens por dois medidores visuais proporcionais em paralelo: Medidor da Janela Ativa/Horaria (5h no Claude, 3h no Codex, diaria no Gemini) e Medidor da Janela Semanal (7 dias), ambos com barras de progresso coloridas por limiares (verde < 70%, amarelo 70-90%, vermelho > 90%), porcentagem em destaque, tokens e contadores regressivos claros.

**Blocked by:** 07: Backend e Contrato do Medidor Percentual Semanal e CLI `--add-account`

**Status:** closed

- [x] Remocao dos textos brutos de quantidade de mensagens como capacidade principal.
- [x] Renderizacao da barra de progresso da Janela Ativa com porcentagem, volume de tokens e tempo de liberacao.
- [x] Renderizacao da barra de progresso da Janela Semanal com porcentagem da semana, volume acumulado de tokens e data/hora de virada do ciclo.
- [x] Unificacao das faixas de cores em ambos os medidores (verde < 70%, amarelo 70-90%, vermelho > 90%).
- [x] Preservacao do badge e acao de copia segura de convites de teste gratuito.
- [x] Revalidacao sintatica do QML com `qml6` e testes automatizados de bindings de contrato.
