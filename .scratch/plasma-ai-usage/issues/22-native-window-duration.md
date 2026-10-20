# 22: Janela Nativa com duração informada pelo provedor

**Parent:** #8

**What to build:** A Janela Nativa de cada provedor passa a usar a duração informada pelo provedor (Claude e Codex pela janela primária da API de uso; Gemini pelo resumo de cota); a constante fixa vira apenas fallback da heurística local. O contrato expõe a duração em segundos e a fração decorrida de cada janela (nativa e semanal), e os cards atuais mostram a marca de tempo decorrido.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Codex deixa de assumir 3h quando a API informa a duração.
- [ ] Contrato traz duração (s) e fração decorrida para Janela Nativa e semanal; campos opcionais, versão do contrato incrementada.
- [ ] Fallback para a constante quando o provedor não informa.
- [ ] Cards atuais exibem a marca de tempo decorrido.
- [ ] Testes de extratores e contrato.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
