# 30: Nota de mudança de limites

**Parent:** #8

**What to build:** Quando um provedor muda seus limites (janela nova, removida, duração diferente ou reset antecipado), o card e a dica exibem uma nota por 3 dias.

**Blocked by:** 22 (#13)

**Status:** ready-for-agent

- [ ] Cada tipo de mudança é detectado comparando com o último estado em cache.
- [ ] Nota expira após 3 dias.
- [ ] Testes pela CLI.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
