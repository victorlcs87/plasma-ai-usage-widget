# 28: Detalhamento Claude (modelo/projeto, uso extra) e Codex (créditos, modelo)

**Parent:** #8

**What to build:** O contrato e os cards passam a mostrar: no Claude, tokens desde o último reset semanal por modelo e por projeto (repositório Git; só desta máquina) e uso extra (gasto e limite mensal) quando a conta o tiver; no Codex, créditos e modelo atual quando disponíveis.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Campos ausentes na API não quebram nem aparecem vazios.
- [ ] Detalhamento por projeto agrupa por repositório Git.
- [ ] Testes de extratores com respostas e logs simulados.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
