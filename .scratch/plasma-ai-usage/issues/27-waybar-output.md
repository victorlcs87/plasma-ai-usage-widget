# 27: Saída de status para Waybar

**Parent:** #8

**What to build:** Nova opção da CLI que imprime status em JSON no formato do Waybar (text, tooltip, class), com classes `normal`, `warning` e `critical` derivadas do nível de alerta.

**Blocked by:** 24 (#15)

**Status:** ready-for-agent

- [ ] Saída válida para o módulo custom do Waybar.
- [ ] Classe reflete o pior nível entre as Contas Ativas no Sistema.
- [ ] Testes pela CLI.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
