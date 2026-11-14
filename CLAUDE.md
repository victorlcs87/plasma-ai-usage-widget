## Agent skills

### Issue tracker

Issues e specs ficam no GitHub Issues do repo (gh CLI); a Spec 05 é a issue #8, com os tickets 18–42 como sub-issues. Ver `docs/agents/issue-tracker.md`.

### Triage labels

Vocabulário padrão: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. Ver `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` é o glossário e `docs/adr/` guarda as decisões. Ver `docs/agents/domain.md`.

## Convenções globais

- Toda conversa com o Claude Code deve ser em português do Brasil.
- Toda tarefa de código deve usar as skills `impeccable` (design/UI) e `ponytail` (simplicidade, evitar over-engineering) quando aplicável.
- Sempre que precisar de senha sudo, pedir a senha via askpass (nunca solicitar a senha diretamente no chat).

## Fluxo obrigatório de desenvolvimento (Matt Pocock)

Vale para toda solicitação de desenvolvimento, feature, correção ou refatoração, em todo projeto.
É inegociável: não pule etapas nem vá direto ao código. Só fica de fora o que não gera código
(perguntas, explicações, leitura).

Motivo: manter cada sessão de código abaixo de ~140k tokens, onde a atenção do modelo ainda é
boa. Por isso o trabalho é alinhado, especificado e fatiado antes de ser escrito.

1. **Interrogatório.** `/mattpocock-skills:grill-with-docs`. Aja como tech lead sênior:
   perguntas difíceis, desafie a arquitetura, ache casos não pensados, acerte a terminologia.
   Nada de código. Saída: escopo claro, `CONTEXT.md` atualizado e um ADR se houver decisão
   arquitetural importante e irreversível.
2. **Spec.** `/mattpocock-skills:to-spec`. Consolide a discussão num documento técnico com arquitetura, regras
   de negócio e como construir. **Pare e espere minha aprovação.**
3. **Tickets.** `/mattpocock-skills:to-tickets`. Fatie o spec aprovado em tickets atômicos, cada um resolvível
   numa única sessão.
4. **Implementação isolada.** `/mattpocock-skills:implement`, um ticket por vez, cada um em contexto limpo
   (sub-agente novo ou sessão nova após `/clear`). Rode tipagem e build.
5. **Revisão imparcial.** `/mattpocock-skills:code-review` de cada ticket, sempre num sub-agente ou sessão
   limpa, nunca no mesmo contexto que escreveu o código.
6. **Gate.** Antes do merge de cada PR, rode a skill `gate`.

Checklist por tarefa, nesta ordem: grill → `CONTEXT.md` → spec lido e aprovado → tickets →
implement do ticket N em contexto novo → code-review do ticket N em contexto novo → gate →
repetir para o próximo ticket.

`grill-with-docs`, `to-spec`, `to-tickets` e `implement` têm `disable-model-invocation: true`:
só eu (usuário) consigo chamá-las pelo `/`. Quando a etapa for sua, leia e siga o `SKILL.md`
dela em `~/.claude/plugins/cache/*/mattpocock-skills/*/skills/` (ou use as que você pode
invocar: `grilling` + `domain-modeling` equivalem a `grill-with-docs`).

## Gate antes do merge

Todo PR, todo projeto: rode a skill `gate` antes do merge (UI 3× só se o PR toca UI, `/security-review`, CI verde).
Achado sem correção, ou correção discutível: pare e me apresente, sem merge.
