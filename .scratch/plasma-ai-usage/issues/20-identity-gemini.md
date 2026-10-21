# 20: Identidade da Conta — Gemini (arquivo e chaveiro)

**Parent:** #8

**What to build:** Aplica ao Gemini o mesmo comportamento, usando o email da conta Google ativa como Identidade da Conta, considerando arquivo de credenciais e chaveiro. Token válido no chaveiro prevalece sobre arquivo com expiração antiga; a cópia atômica (0600) do chaveiro para o arquivo é mantida; token renovado pelo próprio coletor fica só em memória. A troca aplica a credencial no arquivo e no chaveiro (ADR-0008; absorve a #7).

**Blocked by:** 18 (#9)

**Status:** ready-for-agent

- [ ] Mesmos cenários de aceitação do ticket do Claude, verificados para o Gemini.
- [ ] Chaveiro válido + arquivo com expiração antiga ⇒ status `valid`, sem `session_expired`.
- [ ] Token renovado pelo coletor nunca é gravado em disco.
- [ ] Testes pela CLI para o Gemini com chaveiro simulado.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
