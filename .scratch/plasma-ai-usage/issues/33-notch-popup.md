# 33: Popup Notch escuro em cards

**Parent:** #8

**What to build:** A representação completa vira um Notch escuro com cards por provedor e Conta: anéis, contagem regressiva ao vivo (1 s, só com popup aberto), previsão, histórico/gráfico e detalhamentos; ordem e visibilidade dos cards configuráveis; alternar usado ↔ restante e contagem ↔ data; opacidade de fundo. Mantém todas as ações de Conta (criar, renomear, remover, alternar, capturar, login interativo, convites). Configuração reorganizada em abas (Geral, Painel, Popup, Contas, Notificações).

**Blocked by:** 31 (#22), 26 (#17), 28 (#19)

**Status:** ready-for-agent

- [ ] Todas as ações de Conta existentes continuam funcionando no novo popup.
- [ ] Preferências usado/restante e contagem/data aplicadas em todo o widget.
- [ ] Testes estruturais/sintaxe QML; verificação visual; `impeccable`.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
