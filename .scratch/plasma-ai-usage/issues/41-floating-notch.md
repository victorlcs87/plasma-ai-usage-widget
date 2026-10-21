# 41: Notch flutuante preso à borda (opcional)

**Parent:** #8

**What to build:** Opção de exibir o Notch como janela própria presa a qualquer das quatro bordas da tela, independente do painel: arrastar ao longo da borda, recentralizar, tamanho, posição lembrada por borda, sem deslocar quando painéis aparecem/somem. Reutiliza os componentes e o contrato existentes.

**Blocked by:** 33 (#24), 34 (#25), 35 (#26), 40 (#31)

**Status:** ready-for-agent

- [ ] Funciona nas quatro bordas em Wayland e X11 (documentar limitações).
- [ ] Desligado por padrão; não altera o modo Plasmoid.
- [ ] Verificação visual; `impeccable`.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
