# 42: Histórico de Tokens atribuído pela Identidade da Conta

**Parent:** #8 (issue #33)

**What to build:** O Histórico de Tokens passa a ser atribuído pela **Identidade da Conta** (ADR-0008), e não pelo identificador da Conta nem pela "conta ativa no momento da leitura". Isso corrige dois defeitos do ticket 26 (#17): (1) tokens lidos dos logs do caminho do sistema podem ir para a Conta errada se o usuário trocar de conta entre duas coletas; (2) renomear, fundir ou migrar Contas (ticket 18) não pode deixar órfãos nem zerar o histórico acumulado.  Comportamento: antes de qualquer Alternância de Conta, o coletor fecha a leitura incremental dos logs do caminho do sistema e atribui tudo à identidade que está saindo; o histórico é guardado por identidade (Claude: `accountUuid`; Codex: `account_id`) e exibido na Conta que hoje tem aquela identidade. Quando duas Contas são fundidas por identidade, os históricos somam sem duplicar. Na primeira execução, o acumulado antigo dos logs do sistema é atribuído à identidade ativa naquele momento e fica marcado como "estimado" no contrato (sem como saber de quem era antes).

**Blocked by:** 18 (#9), 19 (#10), 26 (#17)

**Status:** ready-for-agent

- [ ] Histórico gravado por identidade; a exibição por Conta resolve identidade → Conta atual (renomear não perde histórico).
- [ ] A troca de conta faz a leitura incremental dos logs do sistema ANTES de aplicar a nova credencial, atribuindo os tokens à identidade de saída; teste A→B→A com consumo entre trocas, cada conta com seu total.
- [ ] Fusão de Contas por identidade soma históricos sem contar duas vezes; migração do `default` legado preserva o histórico existente (formato antigo é convertido automaticamente, idempotente).
- [ ] Credencial desconhecida capturada como Conta nova na troca recebe os tokens do período anterior corretamente.
- [ ] O acumulado inicial (primeira execução) é atribuído à identidade ativa e marcado como estimado no contrato; o card indica isso.
- [ ] Vale para Claude e Codex (Gemini continua sem histórico incremental, limitação já documentada).
- [ ] Testes pela CLI/`status.json` (ponto único de teste da spec).
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
