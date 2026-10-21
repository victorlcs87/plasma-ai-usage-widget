# 21: Perfis Órfãos: listar, reimportar e excluir com confirmação

**Parent:** #8

**What to build:** O usuário vê Perfis Órfãos (Perfil Isolado em disco sem Conta cadastrada) na CLI e no Plasmoid e pode reimportá-los como Conta ou excluí-los mediante confirmação explícita. Nada é apagado automaticamente.

**Blocked by:** 18 (#9)

**Status:** ready-for-agent

- [ ] CLI lista órfãos de todos os provedores; status expõe a lista.
- [ ] Reimportar cria Conta com a identidade do perfil (fundindo se já existir).
- [ ] Excluir exige confirmação explícita (flag na CLI, diálogo na GUI).
- [ ] Migrações e trocas nunca apagam órfãos.
- [ ] Testes pela CLI.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
