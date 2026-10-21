# 39: Verificação de atualização

**Parent:** #8

**What to build:** Uma vez por dia (desligável), o coletor consulta GitHub Releases do widget e a versão no npm de Claude Code, Codex e Gemini CLI, comparando com as versões locais; o painel mostra selo/ponto e o popup indica a nova versão.

**Blocked by:** 31 (#22)

**Status:** ready-for-agent

- [ ] No máximo uma consulta por dia; desligável.
- [ ] Falha de rede não gera erro visível.
- [ ] Testes pela CLI com respostas simuladas.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
