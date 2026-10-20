# 19: Identidade da Conta — Codex

**Parent:** #8

**What to build:** Aplica ao Codex o mesmo comportamento do ticket de identidade do Claude, usando o `account_id` do JWT como Identidade da Conta: detecção correta, migração/fusão da entrada `default`, backup antes da troca, captura de credencial desconhecida e rollback (ADR-0008).

**Blocked by:** 18 (#9)

**Status:** ready-for-agent

- [ ] Mesmos cenários de aceitação do ticket do Claude, verificados para o Codex (incluindo rotação de tokens e `default` legado).
- [ ] Testes pela CLI para o Codex.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
